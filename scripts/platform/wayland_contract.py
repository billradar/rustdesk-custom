#!/usr/bin/env python3
"""Negative contracts for unattended builds, independent of expensive native builds."""
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.platform import wayland
from scripts.platform.platform_package import validate_wayland_deb, sha

ROOT = wayland.ROOT


class WorkflowContract(unittest.TestCase):
    def test_reusable_same_source_flow_is_integrated_into_both_channels(self):
        w = yaml.safe_load((ROOT/'.github/workflows/wayland.yml').read_text())
        self.assertEqual(set(w['on']), {'workflow_call'})
        self.assertEqual(w['permissions'], {'contents':'read','actions':'read'})
        self.assertEqual(set(w['jobs']), {'build','aggregate'})
        b = w['jobs']['build']
        self.assertFalse(b['strategy']['fail-fast'])
        self.assertEqual(b['strategy']['matrix']['include'],
            [{'arch':t['arch'],'runner':t['runner']} for t in wayland.policy()['targets']])
        self.assertEqual(b['with']['source_artifact'], '${{ inputs.standard_artifact }}')
        self.assertEqual(b['with']['channel'], '${{ inputs.channel }}')
        self.assertEqual(b['with']['variant'], 'standard')
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

    def test_release_assets_require_both_arches_parent_source_and_channel(self):
        template={'build_flavor':'unattended-wayland','platform':'linux','variant':'standard',
                  'wayland_policy_sha256':sha(wayland.POLICY),'upstream_sha':'a'*40,
                  'upstream_version':'1.5.1','custom_repository_sha':'b'*40,'build_run':'42',
                  'patchset':'v2','common_patch_hash':'common','prepared_source_identity':'manifest',
                  'prepare_run':'42','server_config_fingerprint':'config'}
        env={'UPSTREAM_EXPECTED_SHA':'a'*40,'UPSTREAM_VERSION':'1.5.1','GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'42','PATCHSET':'v2'}
        canonical=wayland.policy()
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,env):
            root=Path(td);packages=root/'targets';infos={}
            for arch in ['x86_64','aarch64']:
                d=packages/arch;d.mkdir(parents=True);(d/'packages').mkdir()
                (d/'packages'/('client-'+arch+'.deb')).write_bytes(arch.encode())
                (d/'build-info.json').write_text('{}');infos[d]=dict(template,architecture=arch)
            with patch.object(wayland,'ROOT',root),patch.object(wayland,'policy',return_value=canonical),patch.object(wayland,'validate',side_effect=lambda d:infos[d]):
                for channel in ['stable','nightly']:
                    for i in infos.values():i['channel']=channel
                    with patch.dict(os.environ,BUILD_CHANNEL=channel):
                        assets=root/channel;assets.mkdir()
                        report=wayland.attach_assets(packages,assets,template,channel)
                        self.assertEqual(len(list(assets.glob('*.deb'))),2)
                        self.assertEqual(report['channel'],channel)
                        for key in ['prepared_source_identity','prepare_run','common_patch_hash','server_config_fingerprint']:
                            bad=root/(channel+'-'+key);bad.mkdir()
                            with self.assertRaisesRegex(ValueError,'source or configuration mismatch'):
                                wayland.attach_assets(packages,bad,dict(template,**{key:'other'}),channel)
                        with self.assertRaisesRegex(ValueError,'collision'):wayland.attach_assets(packages,assets,template,channel)
                with patch.dict(os.environ,BUILD_CHANNEL='nightly'),self.assertRaises(ValueError):
                    wayland.attach_assets(packages,root,template,'stable')
                (packages/'aarch64/build-info.json').unlink()
                with patch.dict(os.environ,BUILD_CHANNEL='nightly'),self.assertRaises(ValueError):
                    wayland.attach_assets(packages,root,template,'nightly')

    def test_aggregate_rejects_missing_duplicate_stale_and_flavor(self):
        env={'BUILD_CHANNEL':'stable','UPSTREAM_EXPECTED_SHA':'a'*40,'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'42',
             'UPSTREAM_VERSION':'1.5.0','PATCHSET':'v2'}
        template={'build_flavor':'unattended-wayland','platform':'linux','variant':'standard',
            'channel':'stable','wayland_policy_sha256':sha(wayland.POLICY),'upstream_sha':'a'*40,
            'custom_repository_sha':'b'*40,'build_run':'42','patchset':'v2',
            'upstream_version':'1.5.0','common_patch_hash':'common'}
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,env):
            root=Path(td)
            infos={}
            for arch in ['x86_64','aarch64']:
                d=root/arch;d.mkdir();(d/'packages').mkdir();(d/'packages/client.deb').write_bytes(b'package')
                (d/'build-info.json').write_text('{}')
                infos[d]=dict(template,architecture=arch)
            def valid(d):return infos[d]
            with patch.object(wayland,'validate',side_effect=valid):
                wayland.aggregate(root,root/'result.json')
                for field,value in [('channel','nightly'),('build_flavor','standard'),('build_run','41'),('architecture','x86_64'),('wayland_policy_sha256','wrong')]:
                    original=infos[root/'aarch64'];infos[root/'aarch64']=dict(original,**{field:value})
                    with self.assertRaises(ValueError):wayland.aggregate(root,root/'bad.json')
                    infos[root/'aarch64']=original
                (root/'aarch64/build-info.json').unlink()
                with self.assertRaises(ValueError):wayland.aggregate(root,root/'missing.json')


class SourceContract(unittest.TestCase):
    def test_capture_pin_is_bound_to_prepared_packaging_source(self):
        for p in wayland.profiles():
            info={'libdrmtap_sha':p['libdrmtap_sha']}
            wayland.validate_source_policy(info,{'files':{'build.py':p['build_py_sha256']}})
            with self.assertRaisesRegex(ValueError,'prepared packaging source'):
                wayland.validate_source_policy(info,{'files':{'build.py':'wrong'}})
        with self.assertRaisesRegex(ValueError,'unreviewed'):wayland.policy_for_pin('unknown')

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


class PackageContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.info={'architecture':'x86_64','variant':'standard','channel':'stable',
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
            'Replaces':'rustdesk','Depends':'libc6 (>= 2.35), libdrm2 (>= 2.4.101), libegl1, libgles2'}
        self.deb=Path('unattended-wayland-rustdesk-unattended-wayland-1.5.0.deb')

    def check(self):
        with patch('scripts.platform.platform_package.subprocess.check_output',side_effect=lambda a,**kw:self.fields[a[-1]]):
            validate_wayland_deb(self.deb,self.root,self.info)

    def test_correct_package_passes(self):self.check()

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
