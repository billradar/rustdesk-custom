#!/usr/bin/env python3
"""Release qualification, target matrix and workflow dependency contracts."""
import hashlib,json,os,struct,sys,tempfile,unittest
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
        self.assertIn('ENGINE_LIBRARY_SHA256',arm_steps)
        self.assertEqual(set(platforms['jobs']),{'plan','platforms'})
        self.assertEqual(platforms['jobs']['platforms']['needs'],'plan')
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
    def test_missing_required_target_fails_and_report_survives(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(qualification,'ROOT',Path(tmp)),patch.object(qualification,'plan',return_value={'selected':[{'id':'windows-x86_64-standard','required':True,'support_status':'SUPPORTED','variant':'standard'}]}),patch.dict(os.environ,{'UPSTREAM_EXPECTED_SHA':'a'*40,'PATCHSET':'v999999','GITHUB_RUN_ID':'123','GITHUB_SHA':'b'*40}):
            with self.assertRaises(ValueError):qualification.aggregate(Path(tmp),'stable',False)
            self.assertEqual(json.loads((Path(tmp)/'.work/qualification-aggregate/aggregate.json').read_text())['required_gate'],'FAIL')
    def test_untagged_draft_is_handled_by_release_preflight(self):
        import scripts.release.channel as channel
        sha='6c578292e8ebbbec708b76986ba8c4bc7c509747'
        patchset='v999999'
        custom='b'*40
        identity=channel.build_identity(sha,patchset,'c'*64,'d'*64,custom,False)
        name='v1.4.9-custom.v999999.1'
        assets=['SHA256SUMS','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']
        draft={'draft':True,'name':name,'prerelease':False,'tag_name':'untagged-example',
               'body':'\n'.join(['Patch Set: '+patchset,'Upstream SHA: '+sha,'Common Patch Hash: '+'c'*64,'SOS Patch Hash: '+'d'*64,
                   'Custom Repository SHA: '+custom,'Wayland Included: false','Patch Revision: v999999.1','Build Identity: '+identity,
                   'Automation-State: complete','Asset Inventory: '+json.dumps(assets)]),
               'assets':[{'name':n,'state':'uploaded','size':1,'digest':'sha256:'+'a'*64} for n in assets]}
        def api(path,**kwargs):
            if path.startswith('repos/'+channel.REPOSITORY+'/releases/tags/'): return None
            if path.endswith('releases?per_page=100&page=1'): return [draft]
            return None
        with patch.dict(os.environ,GITHUB_SHA=custom,INCLUDE_WAYLAND='false'),patch.object(channel,'api',side_effect=api),patch.object(channel,'patch_hash',side_effect=lambda folder,name: 'c'*64 if folder=='common' else 'd'*64),patch.object(channel,'release_rows',return_value=[draft]),patch.object(channel,'verify'),patch.object(channel,'verify_release_asset_checksums',return_value=True),patch.object(channel,'matching_drafts',return_value=[draft]):
            data=channel.release_preflight({'channel':'stable','version':'1.4.9','upstream_sha':sha,'upstream_tag':'1.4.9','upstream_ref':'1.4.9','patchset':patchset})
            self.assertFalse(data['build_needed'])
            self.assertFalse(data['draft_needed'])
            self.assertEqual(data['release_tag'],name)
            self.assertEqual(data['patch_revision'],'v999999.1')


"""Release qualification and workflow dependency contracts."""
from pathlib import Path
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[2]

class NamingContractTests(unittest.TestCase):
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

    def test_custom_metadata_is_last_and_uses_key_value_contract(self):
        official='# 1.5.0\n\n# Changelog\n'
        metadata=['upstream_sha='+'a'*40,'patchset=v2','release_policy=DRAFT ONLY; publication is a manual user decision','automation_state=complete']
        body=qualification.build_release_body(official,metadata)
        self.assertTrue(body.startswith(official.rstrip()))
        self.assertNotIn('RustDesk Server Pro',body)
        self.assertLess(body.index('# Changelog'),body.index('## Custom release metadata'))
        self.assertEqual(body.rstrip().splitlines()[-1],'automation_state=complete')
        self.assertIn('release_policy=DRAFT ONLY; publication is a manual user decision',body)
        self.assertIn('upstream_sha='+'a'*40,body)

    def test_existing_stable_draft_publish_rechecks_identity_and_asset_inventory(self):
        import scripts.release.channel as channel
        upstream='a'*40;custom='b'*40;patchset='v1'
        common=channel.patch_hash('common',patchset);sos=channel.patch_hash('sos',patchset)
        identity=channel.build_identity(upstream,patchset,common,sos,custom,False)
        names=['SHA256SUMS']
        body='\n'.join(['automation_state=complete','build_package_checksum_architecture_provenance=PASS',
            'build_identity='+identity,'upstream_sha='+upstream,'custom_repository_sha='+custom,'patchset='+patchset,
            'common_patch_hash='+common,'sos_patch_hash='+sos,'wayland_included=false','asset_inventory='+json.dumps(names)])
        release={'id':7,'draft':True,'prerelease':False,'body':body,
                 'assets':[{'name':'SHA256SUMS','state':'uploaded','size':10,'digest':'sha256:'+'c'*64}]}
        env={'GITHUB_REPOSITORY':'billradar/rustdesk-custom','RELEASE_TAG':'v1.4.9-custom.v1.1',
             'BUILD_IDENTITY':identity,'UPSTREAM_SHA':upstream,'CUSTOM_REPOSITORY_SHA':custom,
             'PATCHSET':patchset,'WAYLAND_INCLUDED':'false','WAYLAND_POLICY_SHA256':''}
        with patch.dict(os.environ,env),patch.object(channel,'matching_drafts',return_value=[release]),patch.object(channel,'verify_release_asset_checksums',return_value=True),patch('scripts.release.github.request',return_value={'draft':False}) as write:
            qualification.publish_existing_draft()
            write.assert_called_once()
        mismatch=dict(release,body=body.replace('custom_repository_sha='+custom,'custom_repository_sha='+'d'*40))
        with patch.dict(os.environ,env),patch.object(channel,'matching_drafts',return_value=[mismatch]),patch.object(channel,'verify_release_asset_checksums',return_value=True),patch('scripts.release.github.request') as write:
            with self.assertRaisesRegex(ValueError,'identity differs'):
                qualification.publish_existing_draft()
            write.assert_not_called()

class QualificationSerializationTests(unittest.TestCase):
    def test_release_qualification_writes_real_newlines(self):
        body=qualification.build_release_body(
            '# 1.5.0'+chr(10)+chr(10)+'# Changelog'+chr(10),
            ['upstream_sha='+'a'*40,'patchset=v2','automation_state=complete'],
        )
        self.assertIn(chr(10)+chr(10)+'## Custom release metadata'+chr(10)+chr(10), body)
        self.assertEqual(body.rstrip().splitlines()[-1], 'automation_state=complete')
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
