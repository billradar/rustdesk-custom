"""The reviewed PR-only successor remains CI-only; fixture evidence is not promoted."""
import json
from pathlib import Path
import unittest
from scripts.upstream import patchsets
from scripts.build import macos_arm64_ci as mac, recipe_admission
ROOT=Path(__file__).resolve().parents[2]
BASE='51f94394ce61e1f3d26229565c326b2862cbdd1f'
NEW='a0c0963c483fc8f1aeed4547787d1673adcb583c'
TRANSLATION='45e34a69239c2c2467fd02af8ee97263ff26ef23'

class SourceSuccessorContract(unittest.TestCase):
    def test_review_scope_and_registries(self):
        report=json.loads((ROOT/'metadata/build/a0c0963c-ci-source-review.json').read_text())
        self.assertEqual((report['base_source_sha'],report['candidate_source_sha']),(BASE,NEW))
        self.assertEqual({row['path'] for row in report['changed_entries']},
                         {'.github/pull_request_template.md','.github/workflows/pr-evidence-check.yml'})
        self.assertTrue(all(row['before'] is None for row in report['changed_entries']))
        self.assertFalse(report['stable_allowed'])
        self.assertEqual(report['candidate_actual_package_status'],'NOT_TESTED')
        for path in ('metadata/build/adapter-ci-candidates.json','metadata/platform/ci-candidates.json'):
            rows=json.loads((ROOT/path).read_text())['candidates']
            base={r.get('platform'):r for r in rows if r['source_sha']==BASE}
            candidate={r.get('platform'):r for r in rows if r['source_sha']==NEW}
            self.assertTrue(base)
            self.assertEqual(set(base),set(candidate))
            for platform,row in candidate.items():
                self.assertEqual(row['signature'],base[platform]['signature'])
                self.assertEqual(row['evidence_source_sha'],BASE)
                self.assertFalse(row['stable_allowed'])
                self.assertTrue(row['ci_only'])
        self.assertIn(NEW,mac.REVIEWED_SOURCES)
        self.assertEqual(mac.SOURCE,BASE)

    def test_translation_successor_remains_ci_only(self):
        report=json.loads((ROOT/'metadata/build/45e34a69-ci-source-review.json').read_text())
        self.assertEqual((report['base_source_sha'],report['candidate_source_sha']),(NEW,TRANSLATION))
        self.assertEqual((report['base_leaf_entries'],report['candidate_leaf_entries']),(1113,1113))
        self.assertEqual(report['changed_entries'],[{
            'path':'src/lang/it.rs',
            'before':'100644:e6c86155f484168d8aea4c9d9b772ae78dc22c87',
            'after':'100644:0866942b07e2b7a89ade701b0ace57064659af8a'}])
        self.assertTrue(report['ci_only'])
        self.assertFalse(report['stable_allowed'])
        self.assertFalse(report['release_eligible'])
        self.assertEqual(report['candidate_patch_applicability'],'PENDING_CI')
        self.assertEqual(report['candidate_actual_package_status'],'NOT_TESTED')
        for path in ('metadata/build/adapter-ci-candidates.json','metadata/platform/ci-candidates.json'):
            rows=json.loads((ROOT/path).read_text())['candidates']
            predecessor={r.get('platform'):r for r in rows if r['source_sha']==NEW}
            current={r.get('platform'):r for r in rows if r['source_sha']==TRANSLATION}
            self.assertEqual(set(predecessor),set(current))
            self.assertTrue(current)
            for platform,row in current.items():
                old=predecessor[platform]
                self.assertEqual(row['signature'],old['signature'])
                self.assertEqual(row.get('runners'),old.get('runners'))
                self.assertEqual(row.get('architectures'),old.get('architectures'))
                self.assertEqual(row['evidence_run_id'],old['evidence_run_id'])
                self.assertEqual(row['evidence_source_sha'],BASE)
                self.assertEqual(row['reviewed_predecessor_sha'],NEW)
                self.assertEqual(row['source_comparison'],report['comparison'])
                self.assertTrue(row['ci_only'])
                self.assertFalse(row['stable_allowed'])
        for lane in ('ci','nightly'):
            profile=patchsets.profile_for_version('1.5.3',lane,source_sha=TRANSLATION)
            self.assertEqual(profile['selected'],'v4')
            self.assertTrue(profile['source_match'])
            self.assertTrue(profile['compatibility_test_only'])
        with self.assertRaisesRegex(ValueError,'Stable requires'):
            patchsets.profile_for_version('1.5.3','stable',source_sha=TRANSLATION)
        with self.assertRaisesRegex(ValueError,'unapproved exact source'):
            recipe_admission.source(TRANSLATION)
        self.assertIn(TRANSLATION,mac.REVIEWED_SOURCES)
        self.assertEqual(mac.SOURCE,BASE)
        self.assertEqual(set(recipe_admission.read()['sources']),{BASE,NEW})

    def test_exact_source_only(self):
        for lane in ('ci','nightly'):
            p=patchsets.profile_for_version('1.5.3',lane,source_sha=NEW)
            self.assertEqual(p['selected'],'v4')
            self.assertTrue(p['source_match'])
            self.assertTrue(p['compatibility_test_only'])
        with self.assertRaisesRegex(ValueError,'Stable requires'):
            patchsets.profile_for_version('1.5.3','stable',source_sha=NEW)
        self.assertTrue(patchsets.profile_for_version('1.5.3','ci',source_sha='d'*40)['fallback'])

if __name__=='__main__':
    unittest.main()
