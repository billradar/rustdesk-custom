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
    def test_explicit_policy_and_stable_excludes_experiments(self):
        stable=qualification.plan('stable');night=qualification.plan('nightly',True)
        self.assertTrue(stable['selected'])
        self.assertTrue(night['selected'])
        self.assertTrue(all(e['required'] for e in stable['selected']))
        self.assertFalse(any(e['platform'] in ('android','ios','web') and e['variant']=='sos' for e in night['selected']))
        stable_ids={e['id'] for e in stable['selected']}
        self.assertEqual(len(stable_ids),len(stable['selected']))
        nightly_ids={e['id'] for e in night['selected']}
        self.assertEqual(len(nightly_ids),len(night['selected']))
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
        self.assertEqual(set(windows['jobs']),{'windows-helper','build','validate'})
        self.assertEqual(windows['jobs']['build']['needs'],'windows-helper')
        self.assertEqual(windows['jobs']['validate']['needs'],'build')
        self.assertNotIn('if',windows['jobs']['windows-helper'])
        self.assertNotIn('if',windows['jobs']['build'])
        self.assertNotIn('if',windows['jobs']['validate'])
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
    def test_untagged_draft_deduplicates_without_overwrite(self):
        import scripts.release.channel as channel
        name='v1.4.9-custom.1';sha='6c578292e8ebbbec708b76986ba8c4bc7c509747'
        names=['SHA256SUMS','build-info-standard.json','build-info-sos.json','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']
        draft={'draft':True,'name':name,'prerelease':False,'tag_name':'untagged-example','body':'\n'.join(['Patch Set: v999999','Upstream SHA: '+sha,'Common Patch Hash: '+'c'*64,'SOS Patch Hash: '+'d'*64,'Automation-State: complete']),'assets':[{'name':n,'state':'uploaded'} for n in names]}
        def api(path,**kwargs):return [draft] if path.endswith('releases?per_page=100&page=1') else None
        with patch.object(channel,'api',side_effect=api),patch.object(channel,'choose_stable',return_value={'version':'1.4.9','upstream_sha':sha,'upstream_tag':'1.4.9'}),patch.object(channel,'verify'),patch.object(channel,'patch_hash',side_effect=lambda folder,name: 'c'*64 if folder=='common' else 'd'*64),patch.object(channel,'outputs') as outputs:
            channel.resolve('stable','1.4.9',True)
            data=outputs.call_args.args[0];self.assertTrue(data['build_needed']);self.assertFalse(data['draft_needed'])

"""Release qualification and workflow dependency contracts."""
from pathlib import Path
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[2]

class NamingContractTests(unittest.TestCase):
    def test_standard_has_no_variant_token_and_sos_does(self):
        self.assertEqual(windows_installer_name('1.4.9','standard','exe'), 'rustdesk-1.4.9-windows-x86_64.exe')
        self.assertEqual(windows_installer_name('1.4.9','sos','exe'), 'rustdesk-1.4.9-sos-windows-x86_64.exe')
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
        metadata=['upstream_sha='+'a'*40,'patchset=v2','automation_state=complete']
        body=qualification.build_release_body(official,metadata)
        self.assertTrue(body.startswith(official.rstrip()))
        self.assertNotIn('RustDesk Server Pro',body)
        self.assertLess(body.index('# Changelog'),body.index('## Custom release metadata'))
        self.assertEqual(body.rstrip().splitlines()[-1],'automation_state=complete')
        self.assertIn('upstream_sha='+'a'*40,body)

class QualificationSerializationTests(unittest.TestCase):
    def test_release_qualification_writes_real_newlines(self):
        text=(ROOT/'scripts/release/qualification.py').read_text()
        self.assertNotIn(r"\n", text)
        self.assertIn("target-plan.json');target_plan.write_text(json.dumps(p,indent=2)+'\\n');json.loads(target_plan.read_text())", text)
        self.assertIn("f.write('matrix='+json.dumps({'include':extra},separators=(',',':'))+'\\ncount='", text)

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
        self.assertEqual(tag['aggregate']['needs'],['resolve','draft-preflight','windows-build','platforms-build','android-build','android-sign'])
        self.assertIn('build_needed',tag['aggregate']['outputs'])
        self.assertIn('draft_needed',tag['aggregate']['outputs'])
        self.assertIn('publish_existing',tag['aggregate']['outputs'])
        core=self.workflow('build.yml')['jobs']
        self.assertEqual(core['validate']['needs'],'build')
        self.assertTrue(any(s.get('name')=='Verify shared helper provenance and digest' for s in core['build']['steps']))
        self.assertFalse(any(s.get('name')=='Build official WindowInjection helper' for s in core['build']['steps']))

if __name__ == "__main__": unittest.main()
