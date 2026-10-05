import hashlib,json,os,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import phase5,platform_adapter,platform_package

class MatrixTests(unittest.TestCase):
    def test_explicit_policy_and_stable_excludes_experiments(self):
        stable=phase5.plan('stable');night=phase5.plan('nightly',True)
        self.assertEqual(len(stable['selected']),13)
        self.assertEqual(len(night['selected']),13)
        self.assertTrue(all(e['required'] for e in stable['selected']))
        self.assertFalse(any(e['platform'] in ('android','ios','web') and e['variant']=='sos' for e in night['selected']))
    def test_duplicate_forbidden_and_false_promotion_block(self):
        good=json.loads((ROOT/'metadata/platform-matrix.json').read_text())
        for edit in ('duplicate','android-sos','fake-supported','experimental-required'):
            d=json.loads(json.dumps(good));e=d['entries'][4]
            if edit=='duplicate':d['entries'].append(d['entries'][0])
            if edit=='android-sos':e.update(platform='android',variant='sos')
            if edit=='fake-supported':e.update(support_status='SUPPORTED',evidence_run=None)
            if edit=='experimental-required':e.update(support_status='EXPERIMENTAL',required=True)
            original=json.loads
            def loads(text):
                return d if '"entries"' in text else original(text)
            with patch.object(phase5.json,'loads',side_effect=loads),self.assertRaises(ValueError):phase5.entries()
    def test_parallel_dag_and_gates(self):
        w=yaml.safe_load((ROOT/'.github/workflows/build.yml').read_text());j=w['jobs']
        self.assertEqual(j['build']['needs'],'plan');self.assertEqual(j['platforms']['needs'],'plan');self.assertEqual(j['android-platforms']['needs'],'plan')
        self.assertFalse(j['build']['strategy']['fail-fast']);self.assertFalse(j['platforms']['strategy']['fail-fast'])
        self.assertEqual(j['build']['if'], 'inputs.android_only != true && inputs.other_platforms_only != true')
        self.assertEqual(j['platforms']['if'], "inputs.android_only != true && inputs.windows_only != true && needs.plan.outputs.other_platform_count != '0'")
        self.assertEqual(j['android-platforms']['if'], "inputs.windows_only != true && inputs.other_platforms_only != true && needs.plan.outputs.android_count != '0'")
        self.assertEqual(j['validate']['if'], 'inputs.android_only != true && inputs.windows_only != true && inputs.other_platforms_only != true')
        self.assertIn('inputs.android_only != true', j['aggregate']['if'])
        self.assertIn('inputs.windows_only != true', j['aggregate']['if'])
        self.assertIn('inputs.other_platforms_only != true', j['aggregate']['if'])
        self.assertEqual(set(j['aggregate']['needs']),{'plan','build','platforms','android-platforms','validate'})
        self.assertNotIn('concurrency',j['platforms']);self.assertNotIn('continue-on-error',j['platforms'])
        smoke=yaml.safe_load((ROOT/'.github/workflows/android-yubikey-signing-test.yml').read_text())
        self.assertEqual(smoke['jobs']['build']['with']['android_only'], True)
        t=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        self.assertEqual(t['on']['workflow_dispatch']['inputs']['release_mode']['type'],'choice')
        self.assertEqual(t['on']['workflow_dispatch']['inputs']['release_mode']['options'],['dry-run','draft','release'])
        self.assertNotIn('dry_run',str(t['on']['workflow_dispatch']['inputs']))
        self.assertNotIn('include_experimental',str(t['on']['workflow_dispatch']['inputs']))
        self.assertIn("inputs.release_mode == 'draft'",t['jobs']['draft']['if'])
        self.assertIn("inputs.release_mode == 'release'",t['jobs']['release']['if'])
        self.assertNotIn("inputs.release_mode != 'dry-run'",t['jobs']['android-sign']['if'])
        self.assertNotIn("inputs.release_mode != 'dry-run'",t['jobs']['aggregate']['if'])
        self.assertIn("needs.android-sign.result == 'success'",t['jobs']['aggregate']['if'])
        self.assertNotIn('compatibility',t['jobs'])
        self.assertIn('qualification',t['jobs'])
        self.assertEqual(t['jobs']['qualification']['outputs']['patchset'], "${{ steps.verify.outputs.patchset }}")
        self.assertIn('scripts/ci_qualification.py',t['jobs']['qualification']['steps'][1]['run'])
        for name in ('prepare','windows-build','platforms-build','android-build','android-sign','aggregate','release','draft'):
            self.assertNotIn('compatibility',str(t['jobs'][name].get('needs',[])))
        c=yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())
        self.assertIn('qualification',c['jobs'])
        self.assertIn('ci-qualification-${{ github.sha }}',str(c['jobs']['qualification']))
        self.assertIn('ci-qualification-v1',str((ROOT/'scripts/ci_qualification.py').read_text()))
        self.assertNotIn('schedule',t['on'])
        n=yaml.safe_load((ROOT/'.github/workflows/nightly.yml').read_text())
        self.assertEqual(n['on']['workflow_dispatch']['inputs']['release_mode']['options'], ['build','draft'])
        self.assertNotIn('release', n['on']['workflow_dispatch']['inputs']['release_mode']['options'])
        self.assertIn("inputs.release_mode == 'draft'", n['jobs']['aggregate']['if'])
        self.assertIn("inputs.release_mode == 'draft'", n['jobs']['draft']['if'])
        p=(ROOT/'scripts/phase5.py').read_text()
        self.assertIn("Nightly release is forbidden", p)
        self.assertIn("channel in ('stable','nightly')", p)
        stable=(ROOT/".github/workflows/tag.yml").read_text()
        self.assertNotIn("Authorize Android production signing for this run", stable)
        self.assertNotIn("production_android_signing", stable)
        self.assertIn("needs.android-sign.result == 'success'", stable)
        nightly=(ROOT/".github/workflows/nightly.yml").read_text()
        self.assertNotIn("production_android_signing", nightly)
        self.assertIn("needs.android-sign.result == 'success'", nightly)
        self.assertIn("REQUIRE_ANDROID_PRODUCTION_SIGNING: 'true'", nightly)
        self.assertIn("channel in ('stable','nightly')", p)
        self.assertEqual(t['jobs']['draft']['steps'][-1]['run'],'python3 scripts/phase5.py draft --root .work/collected')
        self.assertEqual(t['jobs']['release']['steps'][-1]['run'],'python3 scripts/phase5.py release --root .work/collected')
        self.assertIn("def release(root, channel='stable'): _release(root, True, channel)",(ROOT/'scripts/phase5.py').read_text())
        n=yaml.safe_load((ROOT/'.github/workflows/nightly.yml').read_text())
        self.assertEqual(n['on']['schedule'],[{'cron':'0 16 * * *'}])
        self.assertIn('draft', n['jobs'])
        router=yaml.safe_load((ROOT/'.github/workflows/upstream-event-router.yml').read_text())
        self.assertIn('schedule', router['on'])
        self.assertIn('master-debounce', router['jobs'])
        self.assertNotIn('test-branch', router['jobs'])
        self.assertIn('stable-tag', router['jobs'])
        self.assertIn('nightly.yml', str(router['jobs']['master-debounce']))
        self.assertNotIn('upstream-compatibility.yml', str(router['jobs']['master-debounce']))
        self.assertIn('ci.yml', str(router['jobs']['stable-tag']))
        self.assertIn("promote_stable=true", str(router['jobs']['stable-tag']))
        phase4=(ROOT/'scripts/phase4.py').read_text()
        self.assertNotIn("Nightly must use official default branch", phase4)
        ci_text=(ROOT/'.github/workflows/ci.yml').read_text()
        self.assertIn('promote_stable', ci_text)
        self.assertIn('ci-bridge-${{ github.sha }}', ci_text)
        tag_text=(ROOT/'.github/workflows/tag.yml').read_text()
        self.assertIn('ci-bridge-${{ github.sha }}', tag_text)
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

class SigningImportTests(unittest.TestCase):
    def test_android_signing_validator_uses_migrated_legacy_module(self):
        source=(ROOT/'scripts/platform_package.py').read_text()
        self.assertIn('from legacy.android_signing import verify_signed',source)
        self.assertNotIn('from android_signing import verify_signed',source)
        import legacy.android_signing as android_signing
        self.assertTrue(callable(android_signing.verify_signed))

class AggregateTests(unittest.TestCase):
    def test_missing_required_target_fails_and_report_survives(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(phase5,'ROOT',Path(tmp)),patch.object(phase5,'plan',return_value={'selected':[{'id':'windows-x86_64-standard','required':True,'support_status':'SUPPORTED','variant':'standard'}]}),patch.dict(os.environ,{'UPSTREAM_EXPECTED_SHA':'a'*40,'PATCHSET':'v1','GITHUB_RUN_ID':'123','GITHUB_SHA':'b'*40}):
            with self.assertRaises(ValueError):phase5.aggregate(Path(tmp),'stable',False)
            self.assertEqual(json.loads((Path(tmp)/'.work/phase5-aggregate/aggregate.json').read_text())['required_gate'],'FAIL')
    def test_untagged_draft_deduplicates_without_overwrite(self):
        import phase4
        name='v1.4.9-custom.1';sha='6c578292e8ebbbec708b76986ba8c4bc7c509747'
        names=['SHA256SUMS','build-info-standard.json','build-info-sos.json','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']
        draft={'draft':True,'name':name,'prerelease':False,'tag_name':'untagged-example','body':'\n'.join(['Patch Set: v1','Upstream SHA: '+sha,'Common Patch Hash: '+phase5.patch_hash('common','v1'),'SOS Patch Hash: '+phase5.patch_hash('sos','v1'),'Automation-State: complete']),'assets':[{'name':n,'state':'uploaded'} for n in names]}
        def api(path,**kwargs):return [draft] if path.endswith('releases?per_page=100&page=1') else None
        with patch.object(phase4,'api',side_effect=api),patch.object(phase4,'choose_stable',return_value={'version':'1.4.9','upstream_sha':sha,'upstream_tag':'1.4.9'}),patch.object(phase4,'outputs') as outputs:
            phase4.resolve('stable','1.4.9',True)
            data=outputs.call_args.args[0];self.assertTrue(data['build_needed']);self.assertFalse(data['draft_needed'])

if __name__=='__main__':unittest.main()
