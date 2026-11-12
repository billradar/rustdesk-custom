#!/usr/bin/env python3
"""Release qualification, target matrix and workflow dependency contracts."""
import contextlib,hashlib,io,json,os,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import yaml
ROOT = Path(__file__).resolve().parents[2]
import scripts.release.qualification as qualification
from scripts.release.naming import native_package_name, windows_installer_name
import scripts.platform.platform_adapter as platform_adapter
import scripts.platform.platform_package as platform_package

class MatrixTests(unittest.TestCase):
    def test_explicit_policy_and_default_experimental_windows_arm64(self):
        stable=qualification.plan('stable')
        self.assertTrue(stable['selected'])
        self.assertTrue(all(e['required'] for e in stable['selected'] if e['support_status']=='SUPPORTED'))
        arm={e['id']:e for e in stable['selected'] if e['platform']=='windows' and e['arch']=='aarch64'}
        self.assertEqual(set(arm),{'windows-aarch64-standard','windows-aarch64-sos'})
        self.assertTrue(all(e['support_status']=='EXPERIMENTAL' and not e['required'] for e in arm.values()))
        self.assertFalse(any(e['arch']=='aarch64' and e['platform']=='windows' for e in qualification.plan('ci')['selected']))
        self.assertFalse(any(e['platform'] in ('android','ios','web') and e['variant']=='sos' for e in stable['selected']))
        stable_ids={e['id'] for e in stable['selected']}
        self.assertEqual(len(stable_ids),len(stable['selected']))
        self.assertEqual(stable_ids, {e['id'] for e in qualification.plan('nightly')['selected']})
    def test_duplicate_forbidden_and_false_promotion_block(self):
        good=json.loads((ROOT/'metadata/platform/matrix.json').read_text())
        for edit in ('duplicate','android-sos','fake-supported','experimental-required'):
            d=json.loads(json.dumps(good));e=d['entries'][4]
            if edit=='duplicate':d['entries'].append(d['entries'][0])
            if edit=='android-sos':e.update(platform='android',variant='sos')
            if edit=='fake-supported':e.update(support_status='SUPPORTED',evidence_run=None)
            if edit=='experimental-required':e.update(support_status='EXPERIMENTAL',required=True)
            original=json.loads
            def loads(text):
                return d if '"entries"' in text else original(text)
            with patch.object(qualification.json,'loads',side_effect=loads),self.assertRaises(ValueError):qualification.entries()
    def test_stable_build_workflows_are_family_specific(self):
        windows=yaml.safe_load((ROOT/'.github/workflows/build-stable-windows.yml').read_text())
        platforms=yaml.safe_load((ROOT/'.github/workflows/build-stable-platforms.yml').read_text())
        android=yaml.safe_load((ROOT/'.github/workflows/build-stable-android.yml').read_text())
        self.assertEqual(set(windows['jobs']),{'windows-helper','build','validate','arm64-bridge','build-arm64','validate-arm64'})
        self.assertEqual(windows['jobs']['build']['needs'],'windows-helper')
        self.assertEqual(windows['jobs']['validate']['needs'],'build')
        self.assertNotIn('if',windows['jobs']['windows-helper'])
        self.assertNotIn('if',windows['jobs']['build'])
        self.assertNotIn('if',windows['jobs']['validate'])
        self.assertEqual(windows['jobs']['arm64-bridge']['runs-on'],'ubuntu-22.04')
        self.assertEqual(windows['jobs']['build-arm64']['runs-on'],'windows-11-arm')
        self.assertEqual(windows['jobs']['validate-arm64']['needs'],'build-arm64')
        arm_steps='\n'.join(s.get('run','') for s in windows['jobs']['build-arm64']['steps'])
        self.assertIn('aarch64-pc-windows-msvc',arm_steps)
        self.assertIn('arm64-windows-static',arm_steps)
        self.assertIn('scripts/build/prepare_windows_arm64_flutter.ps1',arm_steps)
        arm_setup=(ROOT/'scripts/build/prepare_windows_arm64_flutter.ps1').read_text()
        self.assertIn('ENGINE_LIBRARY_SHA256',arm_setup)
        self.assertIn('Get-FileHash $engine -Algorithm SHA256',arm_setup)
        self.assertEqual(set(platforms['jobs']),{'plan','macos-arm64-bridge','platforms'})
        self.assertEqual(platforms['jobs']['platforms']['needs'],['plan','macos-arm64-bridge'])
        self.assertEqual(platforms['jobs']['macos-arm64-bridge']['runs-on'],'ubuntu-22.04')
        self.assertIn('needs.macos-arm64-bridge.outputs.artifact',
                      platforms['jobs']['platforms']['with']['macos_bridge_artifact'])
        self.assertNotIn('if',platforms['jobs']['platforms'])
        self.assertEqual(set(android['jobs']),{'plan','android-platforms'})
        self.assertEqual(android['jobs']['android-platforms']['needs'],'plan')
        self.assertNotIn('if',android['jobs']['android-platforms'])
        for workflow in (windows,platforms,android):
            self.assertEqual(workflow['permissions'],{'contents':'read','actions':'read'})
        tag=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())['jobs']
        self.assertEqual(tag['windows-build']['uses'],'./.github/workflows/build-stable-windows.yml')
        nightly=yaml.safe_load((ROOT/'.github/workflows/nightly.yml').read_text())['jobs']
        self.assertEqual(nightly['windows-build']['uses'],'./.github/workflows/build-stable-windows.yml')
        self.assertEqual(tag['platforms-build']['uses'],'./.github/workflows/build-stable-platforms.yml')
        self.assertEqual(tag['android-build']['uses'],'./.github/workflows/build-stable-android.yml')
        for name in ('windows-build','platforms-build','android-build'):
            self.assertNotIn('windows_only',tag[name].get('with',{}))
            self.assertNotIn('other_platforms_only',tag[name].get('with',{}))
            self.assertNotIn('android_only',tag[name].get('with',{}))
            self.assertNotIn('qualification',str(tag[name].get('needs',[])))


    def test_platforms_consume_source_not_resolver(self):
        w=yaml.safe_load((ROOT/'.github/workflows/build-platform.yml').read_text());steps=w['jobs']['platform-build']['steps'];runs='\n'.join(s.get('run','') for s in steps)
        self.assertIn('prepared_source.py unpack',runs)
        self.assertNotIn('select-patchset',runs);self.assertNotIn('prepare.sh',runs);self.assertNotIn('apply-patches',runs)
        self.assertEqual(w['permissions'],{'contents':'read'})

class AdapterTests(unittest.TestCase):
    def test_reviewed_profiles_and_all_expressions_render(self):
        base=ROOT/'.work/official'
        if not base.exists():self.skipTest('Exact official snapshots not available in unit-test runner')
        for tree in base.iterdir():
            for platform,arch in [('linux','x86_64'),('linux','aarch64'),('macos','x86_64'),('android','aarch64')]:
                p,j=platform_adapter.check(tree,platform,arch)
                self.assertEqual(len(p['signature']),64)
                if platform=='linux':
                    s=next(s for s in j['steps'] if s.get('name')=='Build rustdesk' and 'with' in s)
                    for key in ['run','install']:self.assertNotIn('${{',platform_adapter.render(s['with'][key],p))
    def test_changed_recipe_files_tools_and_disabled_jobs_stay_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);tree=root/'source';tree.mkdir()
            for f in platform_adapter.FILES:
                p=tree/f;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('reviewed')
            wf=tree/'.github/workflows/flutter-build.yml'
            data={'env':{'RUST_VERSION':'1.75','FLUTTER_VERSION':'3.24.5','VCPKG_COMMIT_ID':'a'*40},
                  'jobs':{'build-rustdesk-linux':{'runs-on':'ubuntu-22.04','strategy':{'matrix':{'job':[{'arch':'x86_64','os':'ubuntu-22.04'}]}}}}}
            wf.write_text(yaml.safe_dump(data))
            profile,_=platform_adapter.inspect(tree,'linux','x86_64')
            meta=root/'metadata/platform';meta.mkdir(parents=True)
            approved=meta/'adapter-profiles.json';approved.write_text(json.dumps({'approved':{'linux':[profile['signature']]}}))
            with patch.object(platform_adapter,'ROOT',root):
                platform_adapter.check(tree,'linux','x86_64')
                for file in platform_adapter.FILES:
                    p=tree/file;p.write_text('unreviewed')
                    with self.assertRaisesRegex(ValueError,'unreviewed official'):platform_adapter.check(tree,'linux','x86_64')
                    p.write_text('reviewed')
                data['env']['RUST_VERSION']='1.99';wf.write_text(yaml.safe_dump(data))
                with self.assertRaises(ValueError):platform_adapter.check(tree,'linux','x86_64')
                data['jobs']['build-rustdesk-linux']['if']=False;wf.write_text(yaml.safe_dump(data))
                disabled,_=platform_adapter.inspect(tree,'linux','x86_64')
                approved.write_text(json.dumps({'approved':{'linux':[disabled['signature']]}}))
                with self.assertRaisesRegex(ValueError,'disabled'):platform_adapter.check(tree,'linux','x86_64')

    def test_unknown_expression_blocks(self):
        with self.assertRaises(ValueError):platform_adapter.render('${{ secrets.TEST }}',{'official_matrix':{},'tools':{},'rust':'1.75'})
    def test_unknown_architecture_and_disabled_web_block(self):
        base=ROOT/'.work/official'
        if not base.exists():self.skipTest('Exact official snapshots unavailable')
        tree=next(base.iterdir())
        with self.assertRaises(ValueError):platform_adapter.check(tree,'linux','mips')
        with self.assertRaises(ValueError):platform_adapter.check(tree,'web','web')

class ArchitectureTests(unittest.TestCase):
    def test_elf_architecture_and_bitness(self):
        for arch,cpu,kind in [('x86_64',62,2),('aarch64',183,2),('armv7',40,1)]:
            b=bytearray(64);b[:4]=b'\x7fELF';b[4]=kind;b[5]=1;struct.pack_into('<H',b,18,cpu)
            platform_package.architecture(b,'android',arch)
            with self.assertRaises(ValueError):platform_package.architecture(b,'android','aarch64' if arch!='aarch64' else 'x86_64')
    def test_macho_cpu(self):
        b=b'\xcf\xfa\xed\xfe'+struct.pack('<I',0x100000c)+b'\0'*64
        platform_package.architecture(b,'macos','aarch64')
        with self.assertRaises(ValueError):platform_package.architecture(b,'macos','x86_64')
    def test_checksum_changes_and_duplicate_paths_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a').write_bytes(b'original');platform_package.checksums(root);platform_package.verify_checksums(root)
            (root/'a').write_bytes(b'changed')
            with self.assertRaises(ValueError):platform_package.verify_checksums(root)

class AggregateTests(unittest.TestCase):
    def test_public_name_normalization_is_idempotent(self):
        for variant in ('standard','sos'):
            for arch in ('x86_64','aarch64'):
                for platform,tail in [('linux','.deb'),('linux',f'-0.{arch}.rpm'),
                                      ('linux',f'-0.{arch}-suse.rpm'),('macos','-unsigned.dmg')]:
                    raw=f'{variant}-rustdesk-1.5.1-{arch}{tail}'
                    canonical=native_package_name('1.5.1',variant,platform,arch,raw)
                    self.assertEqual(native_package_name('1.5.1',variant,platform,arch,canonical),canonical)

    def test_all_rpm_names_have_one_architecture_and_distinct_family_selectors(self):
        names=set()
        for variant in ('standard','sos'):
            for arch in ('x86_64','aarch64'):
                for suse in (False,True):
                    tail='-suse.rpm' if suse else '.rpm'
                    raw=f'{variant}-rustdesk-1.5.3-{arch}-0.{arch}{tail}'
                    expected=f'rustdesk-1.5.3'+('-sos' if variant=='sos' else '')+f'-linux-{arch}{tail}'
                    actual=native_package_name('1.5.3',variant,'linux',arch,raw)
                    self.assertEqual(actual,expected);self.assertEqual(actual.count(arch),1)
                    self.assertEqual(native_package_name('1.5.3',variant,'linux',arch,actual),expected)
                    self.assertEqual(native_package_name('1.5.3',variant,'linux',arch,raw,legacy_rpm=True),expected[:-len(tail)]+f'-0.{arch}'+tail)
                    names.add(actual)
        self.assertEqual(len(names),8)
        for bad in ('rustdesk-1.5.3-x86_64-0.aarch64.rpm','rustdesk-1.5.3-x86_64-0.x86_64-debug.rpm'):
            with self.assertRaisesRegex(ValueError,'Unexpected RPM'):native_package_name('1.5.3','standard','linux','x86_64',bad)

    def test_aggregate_uses_new_rpm_names_only_for_new_patch_generations(self):
        for generation in ('v2','v3'):
            with self.subTest(patchset=generation),tempfile.TemporaryDirectory() as td:
                root=Path(td);folder=root/'inputs/target';packages=folder/'packages';packages.mkdir(parents=True)
                info=dict(platform='linux',architecture='aarch64',variant='standard',channel='nightly',upstream_version='1.5.3',upstream_sha='a'*40,patchset=generation,common_patch_hash='c'*64,custom_repository_sha='b'*40,build_run='123',prepared_source_identity='d'*64,server_config_fingerprint='e'*64)
                (folder/'build-info.json').write_text(json.dumps(info))
                for name in ('standard-rustdesk-1.5.3-aarch64-0.aarch64.rpm','standard-rustdesk-1.5.3-aarch64-0.aarch64-suse.rpm'):(packages/name).write_bytes(name.encode())
                target=dict(id='linux-aarch64-standard',platform='linux',arch='aarch64',variant='standard',required=True,support_status='SUPPORTED')
                env=dict(GITHUB_REPOSITORY='billradar/rustdesk-custom',UPSTREAM_EXPECTED_SHA='a'*40,PATCHSET=generation,GITHUB_RUN_ID='123',GITHUB_SHA='b'*40,INCLUDE_WAYLAND='false')
                with patch.dict(os.environ,env),patch.object(qualification,'ROOT',root),patch.object(qualification,'plan',return_value={'selected':[target]}),patch.object(platform_package,'validate'),contextlib.redirect_stdout(io.StringIO()):qualification.aggregate(root/'inputs','nightly',False,release_context={'official_run_id':'17','official_run_url':'https://github.com/rustdesk/rustdesk/actions/runs/17'})
                assets=root/'.work/qualification-aggregate/assets'
                suffix='-0.aarch64' if generation=='v2' else ''
                expected={f'rustdesk-1.5.3-linux-aarch64{suffix}.rpm',f'rustdesk-1.5.3-linux-aarch64{suffix}-suse.rpm','update-manifest.json'}
                self.assertEqual({p.name for p in assets.iterdir()},expected)

    def test_public_name_collision_is_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);first=root/'first';second=root/'second'
            first.write_bytes(b'first');second.write_bytes(b'second');dest=root/'assets'
            with self.assertRaisesRegex(ValueError,'name collision'):
                qualification.stage_assets([(first,'same.deb'),(second,'same.deb')],dest)
            self.assertFalse(dest.exists())
            dest.mkdir();(dest/'same.deb').write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                qualification.stage_assets([(second,'same.deb')],dest)
            self.assertEqual((dest/'same.deb').read_bytes(),b'existing')

    def test_aggregate_collision_cannot_leave_a_pass_report(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'inputs/target';packages=folder/'packages';packages.mkdir(parents=True)
            info=dict(platform='linux',architecture='x86_64',variant='standard',channel='nightly',
                      upstream_version='1.5.1',upstream_sha='a'*40,patchset='v2',common_patch_hash='c'*64,
                      custom_repository_sha='b'*40,build_run='123',prepared_source_identity='d'*64,
                      server_config_fingerprint='e'*64)
            (folder/'build-info.json').write_text(json.dumps(info))
            for name in ('rustdesk-1.5.1-x86_64.deb','standard-rustdesk-1.5.1-x86_64.deb'):
                (packages/name).write_bytes(name.encode())
            entry=dict(id='linux-x86_64-standard',platform='linux',arch='x86_64',variant='standard',
                       required=True,support_status='SUPPORTED')
            env=dict(UPSTREAM_EXPECTED_SHA='a'*40,PATCHSET='v2',GITHUB_RUN_ID='123',GITHUB_SHA='b'*40,INCLUDE_WAYLAND='false')
            with patch.dict(os.environ,env),patch.object(qualification,'ROOT',root),patch.object(
                    qualification,'plan',return_value={'selected':[entry]}),patch.object(
                    platform_package,'validate'),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError,'name collision'):
                    qualification.aggregate(root/'inputs','nightly',False,release_context={'official_run_id':'17','official_run_url':'https://github.com/rustdesk/rustdesk/actions/runs/17'})
            report=json.loads((root/'.work/qualification-aggregate/aggregate.json').read_text())
            self.assertEqual(report['result'],'FAIL');self.assertEqual(report['required_gate'],'FAIL')
            self.assertFalse((root/'.work/qualification-aggregate/assets').exists())

    def test_successful_aggregate_emits_only_the_new_public_manifest(self):
        from scripts.release import attestation
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'inputs/target';packages=folder/'packages';packages.mkdir(parents=True)
            info=dict(platform='linux',architecture='x86_64',variant='standard',channel='nightly',
                      upstream_version='1.5.1',upstream_sha='a'*40,patchset='v2',common_patch_hash='c'*64,
                      custom_repository_sha='b'*40,build_run='123',prepared_source_identity='d'*64,
                      server_config_fingerprint='e'*64,patch_revision='1')
            (folder/'build-info.json').write_text(json.dumps(info))
            (packages/'standard-rustdesk-1.5.1-x86_64.deb').write_bytes(b'validated package')
            target=dict(id='linux-x86_64-standard',platform='linux',arch='x86_64',variant='standard',required=True,support_status='SUPPORTED')
            env=dict(GITHUB_REPOSITORY='billradar/rustdesk-custom',UPSTREAM_EXPECTED_SHA='a'*40,PATCHSET='v2',GITHUB_RUN_ID='123',GITHUB_SHA='b'*40,INCLUDE_WAYLAND='false')
            with patch.dict(os.environ,env),patch.object(qualification,'ROOT',root),patch.object(qualification,'plan',return_value={'selected':[target]}),patch.object(platform_package,'validate'),contextlib.redirect_stdout(io.StringIO()):
                report=qualification.aggregate(root/'inputs','nightly',False,release_context={'official_run_id':'17','official_run_url':'https://github.com/rustdesk/rustdesk/actions/runs/17'})
            self.assertEqual(report['result'],'PASS')
            assets=root/'.work/qualification-aggregate/assets'
            self.assertEqual({p.name for p in assets.iterdir()},{'update-manifest.json','rustdesk-1.5.1-linux-x86_64.deb'})
            manifest=attestation.loads((assets/'update-manifest.json').read_bytes())
            self.assertEqual(manifest['assets'][0]['sha256'],hashlib.sha256(b'validated package').hexdigest())
            self.assertEqual(manifest['build_run'],'123')
            self.assertIsNone(manifest['patch_revision'])

    def test_missing_required_target_fails_and_report_survives(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(qualification,'ROOT',Path(tmp)),patch.object(qualification,'plan',return_value={'selected':[{'id':'windows-x86_64-standard','required':True,'support_status':'SUPPORTED','variant':'standard'}]}),patch.dict(os.environ,{'UPSTREAM_EXPECTED_SHA':'a'*40,'PATCHSET':'v999999','GITHUB_RUN_ID':'123','GITHUB_SHA':'b'*40}):
            with self.assertRaises(ValueError):qualification.aggregate(Path(tmp),'stable',False)
            self.assertEqual(json.loads((Path(tmp)/'.work/qualification-aggregate/aggregate.json').read_text())['required_gate'],'FAIL')
    def test_untagged_draft_is_handled_by_release_preflight(self):
        from scripts.release import attestation
        release=dict(id=7,draft=True,prerelease=False,tag_name='untagged-example',target_commitish='b'*40,assets=[])
        with patch.object(attestation,'read_remote',return_value={'custom_repository_sha':'b'*40}) as read:
            attestation.read_release(release,tag='v1.4.9-custom.v1.2')
        self.assertEqual(read.call_args.args[0],'v1.4.9-custom.v1.2')

    def test_standard_has_no_variant_token_and_sos_does(self):
        self.assertEqual(windows_installer_name('1.4.9','standard','exe'), 'rustdesk-1.4.9-windows-x86_64.exe')
        self.assertEqual(windows_installer_name('1.4.9','sos','exe'), 'rustdesk-1.4.9-sos-windows-x86_64.exe')
        self.assertEqual(windows_installer_name('1.5.1','standard','msi','aarch64'), 'rustdesk-1.5.1-windows-aarch64.msi')
        self.assertEqual(native_package_name('1.4.9','standard','linux','x86_64','standard-rustdesk-1.4.9-x86_64.deb'), 'rustdesk-1.4.9-linux-x86_64.deb')
        self.assertEqual(native_package_name('1.4.9','sos','macos','aarch64','sos-rustdesk-1.4.9-aarch64-unsigned.dmg'), 'rustdesk-1.4.9-sos-macos-aarch64-unsigned.dmg')

    def test_android_standard_name_deduplicates_platform_arch_and_variant(self):
        bad='standard-rustdesk-1.5.0-android-x86_64-standard-android-x86_64-signed.apk'
        self.assertEqual(native_package_name('1.5.0','standard','android','x86_64',bad), 'rustdesk-1.5.0-android-x86_64-signed.apk')
        self.assertEqual(native_package_name('1.5.0','standard','android','aarch64','standard-rustdesk-1.5.0-aarch64.apk'), 'rustdesk-1.5.0-android-aarch64.apk')


class ReleaseBodyContractTests(unittest.TestCase):
    def test_official_release_body_removes_pro_badge(self):
        body='''![image](https://example/image)\n\n[![RustDesk Server Pro](https://img.shields.io/badge/RustDesk%20Server%20Pro-Advanced%20Features-blue)](https://rustdesk.com/pricing.html)\n\n# Changelog\n'''
        normalized=qualification.normalize_release_body(body)
        self.assertNotIn('RustDesk Server Pro',normalized)
        self.assertIn('# Changelog',normalized)

    def test_release_body_is_human_only(self):
        official='# 1.5.0\n\n# Changelog\n'
        self.assertEqual(qualification.build_release_body(official),official)

    def test_existing_stable_draft_publish_rechecks_identity_and_asset_inventory(self):
        import scripts.release.channel as channel
        upstream='a'*40;custom='b'*40;patchset='v1'
        common=channel.patch_hash('common',patchset);sos=channel.patch_hash('sos',patchset)
        identity=channel.build_identity(upstream,patchset,common,sos,custom,False)
        names=['update-manifest.json','release-attestation.json']
        body='\n'.join(['automation_state=complete','build_package_checksum_architecture_provenance=PASS',
            'build_identity='+identity,'upstream_sha='+upstream,'custom_repository_sha='+custom,'patchset='+patchset,
            'common_patch_hash='+common,'sos_patch_hash='+sos,'wayland_included=false','asset_inventory='+json.dumps(names)])
        release={'id':7,'draft':True,'prerelease':False,'body':body,
                 'assets':[{'name':name,'state':'uploaded','size':10,'digest':'sha256:'+'c'*64} for name in names]}
        env={'GITHUB_REPOSITORY':'billradar/rustdesk-custom','RELEASE_TAG':'v1.4.9-custom.v1.1',
             'BUILD_IDENTITY':identity,'UPSTREAM_SHA':upstream,'CUSTOM_REPOSITORY_SHA':custom,
             'PATCHSET':patchset,'WAYLAND_INCLUDED':'false','WAYLAND_POLICY_SHA256':''}
        with patch.dict(os.environ,env),patch.object(channel,'matching_drafts',return_value=[release]),patch('scripts.release.attestation.read_release',return_value={}) as read,patch('scripts.release.github.request',return_value={'draft':False}) as write,patch('scripts.release.stable_tag.ensure') as tag_write:
            qualification.publish_existing_draft()
            tag_write.assert_called_once_with('billradar/rustdesk-custom','v1.4.9-custom.v1.1',custom)
            self.assertEqual(read.call_args.args[2]['custom_repository_sha'],custom)
            self.assertEqual(write.call_args.args[2],{'tag_name':env['RELEASE_TAG'],'target_commitish':custom,'draft':False,'prerelease':False})
        with patch.dict(os.environ,env),patch.object(channel,'matching_drafts',return_value=[release]),patch('scripts.release.attestation.read_release',side_effect=ValueError('identity differs')),patch('scripts.release.github.request') as write:
            with self.assertRaisesRegex(ValueError,'identity differs'):qualification.publish_existing_draft()
            write.assert_not_called()

class QualificationSerializationTests(unittest.TestCase):
    def test_release_qualification_writes_real_newlines(self):
        body=qualification.build_release_body(
            '# 1.5.0'+chr(10)+chr(10)+'# Changelog'+chr(10),
        )
        self.assertEqual(body,'# 1.5.0\n\n# Changelog\n')
        self.assertNotIn('automation_state',body)
        self.assertNotIn('\\n', body)

class ParallelGateTests(unittest.TestCase):
    def workflow(self,name):return yaml.safe_load((ROOT/'.github/workflows'/name).read_text())
    def test_independent_preparations_and_variant_checks(self):
        jobs=self.workflow('compat-check.yml')['jobs']
        self.assertEqual(jobs['bridge']['needs'],['resolve'])
        self.assertEqual(jobs['preflight']['needs'],'resolve')
        self.assertEqual(jobs['windows-helper']['needs'],'resolve')
        self.assertEqual(set(jobs['flutter-analyze']['needs']),{'resolve','bridge'})
        for name in ['preflight','flutter-analyze']:
            self.assertEqual(set(jobs[name]['strategy']['matrix']['variant']),{'standard','sos'})
            self.assertFalse(jobs[name]['strategy']['fail-fast'])
        self.assertEqual(set(jobs['validation-report']['needs']),{'resolve','contracts','preflight','bridge','flutter-analyze','windows-helper'})
        for name in ['preflight','bridge','flutter-analyze','windows-helper']:
            self.assertNotIn('continue-on-error',jobs[name])
    def test_clients_and_draft_remain_downstream_of_complete_compatibility(self):
        tag=self.workflow('tag.yml')['jobs']
        self.assertEqual(set(tag['prepare']['needs']),{'resolve','draft-preflight'})
        self.assertNotIn('qualification',tag['prepare']['needs'])
        self.assertNotIn('qualification',tag['windows-build']['needs'])
        self.assertIn('prepare',tag['windows-build']['needs'])
        self.assertNotIn('qualification',tag['platforms-build']['needs'])
        self.assertIn('prepare',tag['platforms-build']['needs'])
        self.assertNotIn('qualification',tag['android-build']['needs'])
        self.assertIn('prepare',tag['android-build']['needs'])
        self.assertIn('android-build',tag['android-sign']['needs'])
        self.assertEqual(tag['draft']['needs'],'aggregate')
        self.assertEqual(tag['release']['needs'],'aggregate')
        self.assertEqual(tag['publish-existing']['needs'],['resolve','draft-preflight'])
        self.assertEqual(tag['aggregate']['needs'],['resolve','draft-preflight','windows-build','platforms-build','android-build','android-sign','wayland-build'])
        for name in ('publish-existing','release','draft'):
            self.assertIn("github.ref == 'refs/heads/main'",tag[name]['if'])
        self.assertIn('build_needed',tag['aggregate']['outputs'])
        self.assertIn('draft_needed',tag['aggregate']['outputs'])
        self.assertIn('publish_existing',tag['aggregate']['outputs'])
        core=self.workflow('build.yml')['jobs']
        self.assertEqual(core['validate']['needs'],'build')
        self.assertTrue(any(s.get('name')=='Verify shared helper provenance and digest' for s in core['build']['steps']))
        self.assertFalse(any(s.get('name')=='Build official WindowInjection helper' for s in core['build']['steps']))

if __name__ == "__main__": unittest.main()
