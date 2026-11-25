"""Candidate evidence is review input only; release routes use exact source IDs."""
import copy
import json
import unittest
from unittest.mock import patch

from scripts.release import candidate_evidence as evidence, channel, nightly, stable_lock, stable_router
from scripts.upstream import patchsets

APPROVED='95cca3f661f635b3cc85c04935fe8d96d8f432ef'
CANDIDATES=('9724512429b053be04cdb843345e99ddcccdb80e', evidence.SOURCE,
            'a0c0963c483fc8f1aeed4547787d1673adcb583c')

class CandidateEvidenceContract(unittest.TestCase):
    def setUp(self):
        self.record=json.loads(evidence.RECORD.read_text())

    def test_record_covers_exact_fixture_scope_only(self):
        evidence.validate(self.record)
        result=evidence.report(self.record)
        self.assertIn(result['result'],('FIXTURE_VERIFIED','STALE_PATCH_CONTENT','INCOMPLETE_REQUIRED_MATRIX'))
        self.assertEqual(result['verified_fixture_targets'],13)
        self.assertIs(result['release_eligible'],False)

    def test_missing_duplicate_and_forged_approval_fail(self):
        for change in ('missing','duplicate','approval','production'):
            bad=copy.deepcopy(self.record)
            if change=='missing':
                bad['targets'].pop(next(iter(bad['targets'])))
            elif change=='duplicate':
                rows=list(bad['targets'].values());rows[0]['job_id']=rows[1]['job_id']
            elif change=='approval':
                bad['release_eligible']=True
            else:
                bad['production_signing']='PASS'
            with self.subTest(change=change),self.assertRaises(ValueError):
                evidence.validate(bad)

    def test_patch_drift_does_not_promote(self):
        with patch.object(patchsets,'patch_hash',return_value='0'*64):
            result=evidence.report(self.record)
        self.assertEqual(result['result'],'STALE_PATCH_CONTENT')
        self.assertIs(result['release_eligible'],False)

    def test_exact_source_routes_before_dependencies_and_release_lookup(self):
        for sha in CANDIDATES+('a'*40,):
            data={'channel':'stable','upstream_version':'1.5.3','version':'1.5.3',
                  'upstream_tag':'1.5.3','upstream_ref':'1.5.3','upstream_sha':sha}
            with self.subTest(sha=sha):
                selected=patchsets.profile_for_version('1.5.3','ci',source_sha=sha)
                self.assertEqual(selected['selected'],'v4' if sha in CANDIDATES else 'v3')
                self.assertTrue(selected['compatibility_test_only'])
                with patch.object(stable_router,'choose_stable',return_value=data),self.assertRaisesRegex(ValueError,'Stable requires'):
                    stable_router.discovery()
                with self.assertRaisesRegex(ValueError,'Stable requires'):
                    stable_lock.plan(data,selected['selected'])
                with patch.object(channel,'api',side_effect=AssertionError('release lookup forbidden')),self.assertRaisesRegex(ValueError,'Stable requires'):
                    channel.release_preflight(dict(data,patchset=selected['selected']),dry_run=True)
                with self.assertRaisesRegex(ValueError,'Compatibility-test-only'):
                    nightly.require_nightly_build_profile(dict(data,patchset=selected['selected']))
                if sha in CANDIDATES:
                    with self.assertRaisesRegex(ValueError,'differs from selected'):
                        nightly.require_nightly_build_profile(dict(data,patchset='v3'))
        self.assertEqual(patchsets.patchset_for_version('1.5.3','stable',source_sha=APPROVED),'v3')
        self.assertEqual(nightly.require_nightly_build_profile({'upstream_version':'1.5.3',
            'upstream_sha':APPROVED,'patchset':'v3'})['selected'],'v3')
        with self.assertRaisesRegex(ValueError,'exact official source SHA'):
            nightly.require_nightly_build_profile({'upstream_version':'1.5.3','patchset':'v3'})

if __name__=='__main__':
    unittest.main()
