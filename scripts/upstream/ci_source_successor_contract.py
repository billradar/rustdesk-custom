"""The reviewed PR-only successor remains CI-only; fixture evidence is not promoted."""
import json
from pathlib import Path
import unittest
from scripts.upstream import patchsets
from scripts.build import macos_arm64_ci as mac
ROOT=Path(__file__).resolve().parents[2]
BASE='51f94394ce61e1f3d26229565c326b2862cbdd1f'
NEW='a0c0963c483fc8f1aeed4547787d1673adcb583c'

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
