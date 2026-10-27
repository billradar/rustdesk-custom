#!/usr/bin/env python3
"""Negative contracts for unattended builds, independent of expensive native builds."""
import copy
import contextlib
import io
import runpy
import shlex
import json
import os
from pathlib import Path
import struct
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.platform import wayland
from scripts.platform.platform_package import validate_wayland_deb, sha

ROOT = wayland.ROOT


def batch(root, channel='stable'):
    env = {'BUILD_CHANNEL': channel, 'UPSTREAM_EXPECTED_SHA': 'a'*40,
           'GITHUB_SHA': 'b'*40, 'GITHUB_RUN_ID': '42', 'UPSTREAM_VERSION': '1.5.0', 'PATCHSET': 'v2'}
    infos, peers = {}, {}
    for variant in ('standard', 'sos'):
        for arch in ('x86_64', 'aarch64'):
            folder = root / variant / arch
            (folder / 'packages').mkdir(parents=True)
            (folder / 'build-info.json').write_text('{}')
            (folder / 'packages' / wayland.package_name('1.5.0', variant, arch)).write_bytes((variant+arch).encode())
            info = dict(build_flavor='unattended-wayland', platform='linux', variant=variant,
                        architecture=arch, channel=channel, upstream_sha='a'*40, upstream_version='1.5.0',
                        custom_repository_sha='b'*40, build_run='42', patchset='v2', prepare_run='42',
                        common_patch_hash=wayland.patch_hash('common','v2'),
                        sos_patch_hash=wayland.patch_hash('sos','v2') if variant=='sos' else None,
                        prepared_source_identity='manifest-'+variant, server_config_fingerprint='config',
                        libdrmtap_sha=wayland.policy()['libdrmtap_sha'], wayland_policy_sha256=sha(wayland.POLICY))
            infos[folder] = info
            peers[(variant, arch)] = dict(info, build_flavor=None)
    return infos, peers, env


class WorkflowContract(unittest.TestCase):
    def test_reusable_same_source_flow_is_integrated_into_both_channels(self):
        w = yaml.safe_load((ROOT/'.github/workflows/wayland.yml').read_text())
        self.assertEqual(set(w['on']), {'workflow_call'})
        self.assertEqual(w['permissions'], {'contents':'read','actions':'read'})
        self.assertEqual(set(w['jobs']), {'build','aggregate'})
        b = w['jobs']['build']
        self.assertFalse(b['strategy']['fail-fast'])
        self.assertEqual(b['strategy']['matrix']['include'],
            [{'arch':t['arch'],'variant':t['source_variant'],'runner':t['runner']} for t in wayland.policy()['targets']])
        self.assertEqual(b['with']['source_artifact'], "${{ matrix.variant == 'sos' && inputs.sos_artifact || inputs.standard_artifact }}")
        self.assertEqual(b['with']['channel'], '${{ inputs.channel }}')
        self.assertEqual(b['with']['variant'], '${{ matrix.variant }}')
        self.assertEqual(w['jobs']['aggregate']['needs'], 'build')
        for job in w['jobs'].values():
            self.assertNotIn('environment',job)
            self.assertNotIn('permissions',job)
        for file, channel in [('tag.yml','stable'),('nightly.yml','nightly')]:
            parent=yaml.safe_load((ROOT/'.github/workflows'/file).read_text())
            self.assertTrue(parent['on']['workflow_dispatch']['inputs']['include_wayland']['default'])
            call=parent['jobs']['wayland-build']
            self.assertEqual(call['uses'],'./.github/workflows/wayland.yml')
            self.assertEqual(call['with']['channel'],channel)
            self.assertEqual(call['with']['standard_artifact'],'${{ needs.prepare.outputs.standard_artifact }}')
            self.assertEqual(call['with']['sos_artifact'],'${{ needs.prepare.outputs.sos_artifact }}')
            self.assertEqual(set(call['needs']),{'resolve','prepare'})
            self.assertIn('wayland-build',parent['jobs']['aggregate']['needs'])
            self.assertIn("needs.wayland-build.result == 'success'",parent['jobs']['aggregate']['if'])
        tag=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        for name in ['aggregate','draft','release']:
            job=tag['jobs'][name]
            self.assertIn('INCLUDE_WAYLAND',job['env'])
            self.assertTrue(any('wayland-targets' in x.get('with',{}).get('path','') for x in job['steps']))
        for name in ['draft','release']:
            for key in ['PATCHSET','UPSTREAM_EXPECTED_SHA','UPSTREAM_VERSION','BUILD_CONFIGURATION']:
                self.assertIn(key,tag['jobs'][name]['env'])

    def test_target_checks_before_dependencies_and_upload(self):
        w=yaml.safe_load((ROOT/'.github/workflows/build-wayland-target.yml').read_text())
        job=w['jobs']['platform-build'];steps=job['steps']
        self.assertEqual(job['env']['BUILD_FLAVOR'],'unattended-wayland')
        names=[x.get('name','') for x in steps]
        gate=names.index('Fail-closed DRM source and native architecture preflight')
        self.assertLess(gate,next(i for i,x in enumerate(steps) if x.get('id')=='rust'))
        self.assertLess(gate,next(i for i,x in enumerate(steps) if x.get('id')=='vcpkg'))
        upload=next(x for x in steps if x.get('id')=='upload')
        self.assertNotIn('if',upload)
        self.assertTrue(upload['with']['name'].startswith('rustdesk-wayland-'))
        text=(ROOT/'scripts/build/linux_wayland.sh').read_text()
        self.assertNotIn('-e GH_TOKEN',text)
        self.assertNotIn('DRMTAP_ALLOW_UNPINNED',text)
        self.assertIn('wayland.py recipe',text)
        self.assertTrue(all(t['status']=='EXPERIMENTAL' and t['runtime']=='NOT TESTED' for t in wayland.policy()['targets']))

    def test_unattended_cannot_substitute_for_standard_qualification(self):
        from scripts.release import qualification
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'build-info.json').write_text(json.dumps({'platform':'linux','architecture':'x86_64',
                'variant':'standard','build_flavor':'unattended-wayland'}))
            with self.assertRaisesRegex(ValueError,'dedicated build flavor'):
                qualification.aggregate(root,'stable',False)

    def test_release_assets_require_four_targets_and_matching_variant_peers(self):
        for channel in ('stable','nightly'):
            with tempfile.TemporaryDirectory() as td:
                root=Path(td);infos,peers,env=batch(root/'targets',channel)
                assets=root/'assets';assets.mkdir();canonical=wayland.policy()
                with patch.object(wayland,'policy',return_value=canonical),patch.dict(os.environ,env),patch.object(wayland,'ROOT',root),patch.object(wayland,'validate',side_effect=lambda d:infos[d]):
                    report=wayland.attach_assets(root/'targets',assets,peers,channel)
                    self.assertEqual(set(p.name for p in assets.iterdir()),wayland.asset_names('1.5.0'))
                    self.assertEqual(len(report['targets']),4)
                    self.assertEqual(report['schema'],'wayland-qualification-v2')
                    for key in ['prepared_source_identity','prepare_run','common_patch_hash','sos_patch_hash','server_config_fingerprint']:
                        bad=root/key;bad.mkdir()
                        wrong=copy.deepcopy(peers);wrong[('sos','aarch64')][key]='other'
                        with self.assertRaisesRegex(ValueError,'source or configuration mismatch'):
                            wayland.attach_assets(root/'targets',bad,wrong,channel)
                        self.assertFalse(list(bad.iterdir()),'failure must not copy a partial set')
                    bad=root/'missing-peer';bad.mkdir()
                    wrong=dict(peers);wrong.pop(('sos','aarch64'))
                    with self.assertRaisesRegex(ValueError,'peer missing'):
                        wayland.attach_assets(root/'targets',bad,wrong,channel)
                    with self.assertRaisesRegex(ValueError,'collision'):
                        wayland.attach_assets(root/'targets',assets,peers,channel)
                    with self.assertRaisesRegex(ValueError,'channel mismatch'):
                        wayland.attach_assets(root/'targets',assets,peers,'nightly' if channel=='stable' else 'stable')

    def test_aggregate_rejects_missing_duplicate_stale_and_cross_variant(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);infos,peers,env=batch(root/'targets')
            with patch.dict(os.environ,env),patch.object(wayland,'validate',side_effect=lambda d:infos[d]):
                wayland.aggregate(root/'targets',root/'result.json')
                folder=root/'targets/sos/aarch64'
                for field,value in [('channel','nightly'),('build_flavor','standard'),('build_run','41'),
                                    ('architecture','x86_64'),('wayland_policy_sha256','wrong'),
                                    ('sos_patch_hash',None),('variant','standard'),
                                    ('prepared_source_identity','manifest-standard'),('libdrmtap_sha','other')]:
                    with self.subTest(field=field):
                        original=infos[folder];infos[folder]=dict(original,**{field:value})
                        with self.assertRaises(ValueError):wayland.aggregate(root/'targets',root/'bad.json')
                        infos[folder]=original
                for folder in list(infos):
                    infofile=folder/'build-info.json';infofile.unlink()
                    with self.assertRaises(ValueError):wayland.aggregate(root/'targets',root/'missing.json')
                    infofile.write_text('{}')
                duplicate=root/'targets/duplicate';duplicate.mkdir();(duplicate/'build-info.json').write_text('{}')
                infos[duplicate]=dict(next(iter(infos.values())))
                (duplicate/'packages').mkdir()
                (duplicate/'packages'/wayland.package_name('1.5.0','standard','x86_64')).write_bytes(b'duplicate')
                with self.assertRaisesRegex(ValueError,'duplicate'):
                    wayland.aggregate(root/'targets',root/'duplicate.json')
                (duplicate/'build-info.json').unlink()
                for folder in infos:
                    if folder.parts[-2]=='sos':(folder/'build-info.json').unlink()
                with self.assertRaisesRegex(ValueError,'all four'):
                    wayland.aggregate(root/'targets',root/'legacy.json')


class BuildEntrypointContract(unittest.TestCase):
    def test_shell_adapter_command_matches_real_cli_for_every_target(self):
        from scripts.platform.platform_adapter import parse_args
        lines=(ROOT/'scripts/build/linux_wayland.sh').read_text().splitlines()
        command=next(line for line in lines if line.startswith('python3 scripts/platform/platform_adapter.py '))
        recipe=next(line for line in lines if line.startswith('python3 scripts/platform/wayland.py recipe '))
        self.assertIn('--variant "$VARIANT"',recipe)
        for variant in ('standard','sos'):
            for arch in ('x86_64','aarch64'):
                with self.subTest(variant=variant,arch=arch):
                    tokens=shlex.split(command)
                    substitutions={'$source':'/fixture/source','$PLATFORM_ARCH':arch,'$VARIANT':variant}
                    args=[substitutions.get(token,token) for token in tokens[2:]]
                    parsed=parse_args(args)
                    self.assertEqual(parsed.platform,'linux')
                    self.assertEqual(parsed.arch,arch)
                    self.assertEqual(parsed.tree,Path('/fixture/source'))
                    self.assertEqual(parsed.output,Path('.work/platform-profile.json'))

    def run_entrypoint(self,folder,platform,variant,flavor,arch='x86_64'):
        env={'PLATFORM':platform,'PLATFORM_ARCH':arch,'VARIANT':variant,
             'BUILD_FLAVOR':flavor,'GITHUB_RUN_ID':'42','GITHUB_JOB':'fixture',
             'UPSTREAM_EXPECTED_SHA':'a'*40,'PATCHSET':'v2'}
        previous=Path.cwd()
        try:
            os.chdir(folder)
            with patch.dict(os.environ,env,clear=True),patch('subprocess.Popen') as spawn,contextlib.redirect_stdout(io.StringIO()):
                spawn.return_value.stdout=iter(['fixture build completed\n'])
                spawn.return_value.wait.return_value=0
                try:
                    runpy.run_path(str(ROOT/'scripts/platform/run_platform.py'),run_name='__main__')
                except SystemExit as done:
                    self.assertEqual(done.code,0)
                return spawn
        finally:
            os.chdir(previous)

    def test_platform_runner_dispatches_both_variants_to_wayland_builder(self):
        for variant in ('standard','sos'):
            for arch in ('x86_64','aarch64'):
                with self.subTest(variant=variant,arch=arch),tempfile.TemporaryDirectory() as td:
                    root=Path(td);spawn=self.run_entrypoint(root,'linux',variant,'unattended-wayland',arch)
                    self.assertEqual(spawn.call_args.args[0],['bash','scripts/build/linux_wayland.sh'])
                    report=json.loads((root/'.work/target-diagnostic/diagnostic.json').read_text())
                    self.assertEqual(report['result'],'PASS')
                    self.assertEqual(report['target'],'linux-'+arch+'-'+variant)

    def test_runner_still_blocks_wrong_platform_variant_and_flavor(self):
        for platform,variant,flavor in [('macos','sos','unattended-wayland'),
                                         ('linux','unknown','unattended-wayland'),('linux','sos','unknown')]:
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaisesRegex(ValueError,'forbidden build flavor'):
                    self.run_entrypoint(Path(td),platform,variant,flavor)


class SourceContract(unittest.TestCase):
    def test_capture_pin_is_bound_to_prepared_packaging_source(self):
        for p in wayland.profiles():
            info={'libdrmtap_sha':p['libdrmtap_sha']}
            wayland.validate_source_policy(info,{'files':{'build.py':p['build_py_sha256']}})
            with self.assertRaisesRegex(ValueError,'prepared packaging source'):
                wayland.validate_source_policy(info,{'files':{'build.py':'wrong'}})
        with self.assertRaisesRegex(ValueError,'unreviewed'):wayland.policy_for_pin('unknown')

    def test_post_build_arm_rewrites_are_exact_and_source_bound(self):
        original=b'flutter build linux --release\nx64/release\n'
        p=dict(wayland.policy(),build_py_sha256=__import__('hashlib').sha256(original).hexdigest())
        manifest={'upstream_sha':'a'*40,'files':{'build.py':p['build_py_sha256']}}
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,UPSTREAM_EXPECTED_SHA='a'*40):
            tree=Path(td);(tree/'source-manifest.json').write_text(json.dumps(manifest))
            (tree/'.github/workflows').mkdir(parents=True)
            (tree/'.github/workflows/flutter-build.yml').write_text('jobs: {build-rustdesk-linux-drm: {steps: []}}')
            with patch.object(wayland.subprocess,'check_output',return_value=original),patch.object(wayland,'profiles',return_value=[p]),patch.object(wayland.adapter,'digest',return_value=p['upstream_drm_job_sha256']):
                for arch,content in [('x86_64',original),('aarch64',original.replace(b'flutter build linux --release',b'flutter-elinux build linux --verbose').replace(b'x64/release',b'arm64/release'))]:
                    (tree/'build.py').write_bytes(content)
                    self.assertEqual(wayland.policy_for_built_tree(tree,arch)['libdrmtap_sha'],p['libdrmtap_sha'])
                    (tree/'build.py').write_bytes(content+b'unreviewed')
                    with self.assertRaisesRegex(ValueError,'post-build packaging modification'):wayland.policy_for_built_tree(tree,arch)
                (tree/'source-manifest.json').write_text(json.dumps(dict(manifest,upstream_sha='b'*40)))
                with self.assertRaisesRegex(ValueError,'source SHA'):wayland.policy_for_built_tree(tree,'aarch64')
                bad=dict(manifest,files={'build.py':'wrong'})
                (tree/'source-manifest.json').write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError,'prepared inventory'):wayland.policy_for_built_tree(tree,'aarch64')

    def test_prepared_variant_mismatch_is_rejected_before_recipe(self):
        with tempfile.TemporaryDirectory() as td:
            tree=Path(td);(tree/'source-manifest.json').write_text('{"variant":"standard"}')
            with self.assertRaisesRegex(ValueError,'variant mismatch'):
                wayland.preflight(tree,'x86_64','sos')

    def test_standard_and_sos_recipes_keep_drm_wake_tests_and_deb_only(self):
        for variant in ('standard','sos'):
            with tempfile.TemporaryDirectory() as td:
                tree=Path(td);out=tree/'recipe'
                def base(*args):
                    out.mkdir()
                    (out/'build.sh').write_text('cargo build --locked --lib $JOBS --features hwcodec,flutter,unix-file-copy-paste --release\npython3 ./build.py --flutter --skip-cargo\n# rpm package\nunreviewed RPM command\n')
                with patch.object(wayland,'preflight') as gate,patch.object(wayland.adapter,'linux_scripts',side_effect=base),patch.object(wayland,'policy_for_tree',return_value=wayland.policy()):
                    wayland.recipe(tree,'x86_64',out,variant)
                    gate.assert_called_once_with(tree,'x86_64',variant)
                script=(out/'build.sh').read_text()
                self.assertIn('for want in drm drm-wake',script)
                self.assertIn('test "$ran" -gt 0',script)
                self.assertIn('build.py --flutter --drm',script)
                self.assertNotIn('RPM command',script)

    def test_unknown_architecture_fails(self):
        with self.assertRaisesRegex(ValueError,'ARCH:'):
            wayland.preflight(Path('/nonexistent'), 'armv7')

    def test_changed_packaging_and_official_drm_recipe_fail(self):
        with tempfile.TemporaryDirectory() as td:
            tree=Path(td);(tree/'.github/workflows').mkdir(parents=True)
            (tree/'build.py').write_text('unreviewed')
            (tree/'.github/workflows/flutter-build.yml').write_text('jobs: {build-rustdesk-linux-drm: {runs-on: changed}}')
            with patch.object(wayland.adapter,'check',return_value=({'runner':'ubuntu-22.04'},{})):
                with self.assertRaisesRegex(ValueError,'unreviewed official DRM recipe'):
                    wayland.preflight(tree,'x86_64')
                with patch.object(wayland.adapter,'digest',return_value=wayland.policy()['upstream_drm_job_sha256']):
                    with self.assertRaisesRegex(ValueError,'packaging interface'):
                        wayland.preflight(tree,'x86_64')


class DebianLabelContract(unittest.TestCase):
    @unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb needed for real package round-trip')
    def test_variant_switch_keeps_package_identity_payload_and_service_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);stage=root/'stage';(stage/'DEBIAN').mkdir(parents=True)
            (stage/'usr/bin').mkdir(parents=True)
            (stage/'usr/bin/rustdesk').write_bytes(b'fictional unchanged client payload')
            control='Package: rustdesk-unattended-wayland\nVersion: 1.5.0\nArchitecture: amd64\nMaintainer: Fixture <fixture@example.invalid>\nConflicts: rustdesk\nProvides: rustdesk\nReplaces: rustdesk\nDescription: RustDesk\n Original long description.\n'
            (stage/'DEBIAN/control').write_text(control)
            postinst=stage/'DEBIAN/postinst';postinst.write_text('#!/bin/sh\nexit 0\n');postinst.chmod(0o755)
            package=root/'client.deb'
            subprocess.run(['dpkg-deb','-Zxz','--build','--root-owner-group',str(stage),str(package)],check=True,stdout=subprocess.DEVNULL)
            for attempt,variant in enumerate(('standard','sos','standard')):
                wayland.label_package(package,variant)
                values=subprocess.check_output(['dpkg-deb','-f',str(package)],text=True)
                for line in control.splitlines():
                    if not line.startswith(('Description:',' ')):self.assertIn(line,values)
                self.assertIn('Description: RustDesk Wayland unattended ('+variant.upper()+')',values)
                self.assertIn(' Original long description.',values)
                unpack=root/(variant+str(attempt))
                subprocess.run(['dpkg-deb','--raw-extract',str(package),str(unpack)],check=True)
                self.assertEqual((unpack/'usr/bin/rustdesk').read_bytes(),b'fictional unchanged client payload')
                self.assertEqual((unpack/'DEBIAN/postinst').read_bytes(),postinst.read_bytes())
                self.assertEqual((unpack/'DEBIAN/postinst').stat().st_mode & 0o777,0o755)
            with self.assertRaises(ValueError):wayland.label_package(package,'unknown')

    def test_asset_names_are_unique_and_not_old_two_package_names(self):
        names=wayland.asset_names('1.5.0')
        self.assertEqual(len(names),4)
        for variant in ('standard','sos'):
            for arch in ('x86_64','aarch64'):
                self.assertIn(f'rustdesk-unattended-wayland-{variant}-1.5.0-{arch}.deb',names)
        with self.assertRaises(ValueError):wayland.package_name('../bad','sos','x86_64')


class PackageContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.info={'architecture':'x86_64','variant':'standard','channel':'stable','upstream_version':'1.5.0',
            'wayland_policy_sha256':sha(wayland.POLICY),'libdrmtap_sha':wayland.policy()['libdrmtap_sha'],
            'drm_tests':'PASS','drm_test_groups':8,'drm_test_count':8}
        lib=self.root/'usr/lib/rustdesk/libdrmtap.so.0.5.8';lib.parent.mkdir(parents=True)
        data=bytearray(64);data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',data,18,62)
        lib.write_bytes(bytes(data)+b'libEGL.so.1\0eglCreateImageKHR\0GLIBC_2.35')
        (lib.parent/'libdrmtap.so.0').symlink_to(lib.name)
        self.obj=lib
        self.native=self.root/'usr/share/rustdesk/lib/librustdesk.so';self.native.parent.mkdir(parents=True)
        self.native.write_bytes(b'/usr/lib/rustdesk/libdrmtap.so.0\0enable-drm-display-wake')
        self.fields={'Package':'rustdesk-unattended-wayland','Conflicts':'rustdesk','Provides':'rustdesk',
            'Replaces':'rustdesk','Description':'RustDesk Wayland unattended (STANDARD)','Depends':'libc6 (>= 2.35), libdrm2 (>= 2.4.101), libegl1, libgles2'}
        self.deb=Path(wayland.package_name('1.5.0','standard','x86_64'))

    def check(self):
        with patch('scripts.platform.platform_package.subprocess.check_output',side_effect=lambda a,**kw:self.fields[a[-1]]):
            validate_wayland_deb(self.deb,self.root,self.info)

    def test_correct_package_passes(self):self.check()

    def test_sos_package_must_be_labeled_and_named_for_sos(self):
        self.info['variant']='sos'
        with self.assertRaisesRegex(ValueError,'filename'):self.check()
        self.deb=Path(wayland.package_name('1.5.0','sos','x86_64'))
        with self.assertRaisesRegex(ValueError,'description'):self.check()
        self.fields['Description']='RustDesk Wayland unattended (SOS)'
        self.check()


    def test_nightly_profile_requires_its_exact_capture_library_version(self):
        self.info['channel']='nightly'
        self.info['libdrmtap_sha']=wayland.policy()['additional_profiles'][0]['libdrmtap_sha']
        self.info.update(drm_test_groups=12,drm_test_count=12)
        with self.assertRaisesRegex(ValueError,'soname'):self.check()
        obj=self.obj.rename(self.obj.with_name('libdrmtap.so.0.5.12'))
        link=obj.parent/'libdrmtap.so.0';link.unlink();link.symlink_to(obj.name)
        self.check()
        self.info['channel']='ci'
        with self.assertRaisesRegex(ValueError,'source/channel'):self.check()

    def test_stock_name_missing_relationship_and_dependency_fail(self):
        for field in self.fields:
            old=self.fields[field];self.fields[field]='wrong'
            with self.assertRaises(ValueError):self.check()
            self.fields[field]=old

    def test_missing_library_wrong_arch_stub_helper_and_stock_binary_fail(self):
        data=self.obj.read_bytes()
        for blob in [b'bad ELF',data.replace(b'\x3e\x00',b'\xb7\x00',1),data.replace(b'eglCreateImageKHR',b'no-egl'),data+b'/usr/libexec/drmtap-helper']:
            self.obj.write_bytes(blob)
            with self.assertRaises(ValueError):self.check()
        self.obj.write_bytes(data)
        for blob in [b'stock-client',b'/usr/lib/rustdesk/libdrmtap.so.0']:
            self.native.write_bytes(blob)
            with self.assertRaises(ValueError):self.check()

    def test_libc_floor_and_soname_must_match(self):
        self.fields['Depends']=self.fields['Depends'].replace('2.35','2.17')
        with self.assertRaisesRegex(ValueError,'libc6'):self.check()
        self.fields['Depends']=self.fields['Depends'].replace('2.17','2.35')
        (self.obj.parent/'libdrmtap.so.0').unlink()
        (self.obj.parent/'libdrmtap.so.0').symlink_to('/tmp/unrelated')
        with self.assertRaisesRegex(ValueError,'soname'):self.check()

    def test_stale_pin_policy_or_empty_test_execution_fail(self):
        for key,value in [('libdrmtap_sha','bad'),('wayland_policy_sha256','bad'),('drm_test_groups',0),('drm_test_count',0)]:
            old=self.info[key];self.info[key]=value
            with self.assertRaises(ValueError):self.check()
            self.info[key]=old


if __name__=='__main__':unittest.main()
