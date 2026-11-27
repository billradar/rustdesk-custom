"""CI source routing: repository regression baseline vs explicit moving upstream check."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import channel

REVIEWED_SHA='95cca3f661f635b3cc85c04935fe8d96d8f432ef'


class CiBaselineTests(unittest.TestCase):
    def test_reviewed_baseline_matches_exact_source_and_current_patch(self):
        value=channel.ci_baseline()
        self.assertEqual(value['upstream_sha'],REVIEWED_SHA)
        self.assertEqual(value['upstream_version'],'1.5.3')
        self.assertEqual(value['patchset'],'v3')
        self.assertEqual(value['patch_revision'],9)
        self.assertEqual(value['patch_hashes'],channel.verify('v3')['hashes'])
        self.assertEqual(value['validation'],'full-ci-required')

    def test_default_ci_resolves_immutable_baseline_not_official_main(self):
        with patch.object(channel,'api',side_effect=AssertionError('CI queried moving upstream main')), \
             patch.object(channel,'resolve_ref',return_value=REVIEWED_SHA) as lookup, \
             patch.object(channel,'outputs') as output:
            channel.resolve('ci')
        lookup.assert_called_once_with(REVIEWED_SHA)
        result=output.call_args.args[0]
        self.assertEqual(result['upstream_sha'],REVIEWED_SHA)
        self.assertEqual(result['upstream_ref'],REVIEWED_SHA)
        self.assertEqual(result['ci_source_policy'],'reviewed-ci-baseline')
        self.assertEqual(result['channel'],'ci')
        self.assertTrue(result['build_needed'])
        self.assertFalse(result['draft_needed'])

    def test_explicit_ref_keeps_moving_main_monitoring_and_manual_override(self):
        latest_sha='a'*40
        with patch.object(channel,'ci_baseline',side_effect=AssertionError('Explicit source must bypass baseline')), \
             patch.object(channel,'api',side_effect=AssertionError('Unexpected branch discovery')), \
             patch.object(channel,'resolve_ref',return_value=latest_sha) as lookup, \
             patch.object(channel,'outputs') as output:
            channel.resolve('ci','main')
        lookup.assert_called_once_with('main')
        self.assertEqual(output.call_args.args[0]['ci_source_policy'],'explicit-upstream-ref')
        self.assertEqual(output.call_args.args[0]['upstream_sha'],latest_sha)

    def test_baseline_identity_mismatch_fails_before_qualification(self):
        with patch.object(channel,'resolve_ref',return_value='b'*40), \
             patch.object(channel,'outputs') as out, \
             self.assertRaisesRegex(ValueError,'identity mismatch'):
            channel.resolve('ci')
        out.assert_not_called()

    def test_bad_manifest_and_unknown_patchset_fail_closed(self):
        original=channel.ci_baseline()
        cases=[
            dict(original,upstream_sha='main'),
            dict(original,repository='attacker/rustdesk'),
            dict(original,upstream_sha='54416dcaa127d209f2cfbdc4b08235bae78ccfe6'),
            dict(original,patch_revision=7),
            dict(original,patch_hashes={'common':'a'*64,'sos':'b'*64}),
            dict(original,source_review='../unreviewed.json'),
            dict(original,validation='unreviewed'),
            dict(original,patchset='v1'),
            dict(original,upstream_version='1.5.1'),
        ]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'manifest.json'
            for data in cases:
                with self.subTest(data=data):
                    path.write_text(json.dumps(data))
                    with patch.object(channel,'CI_BASELINE',path),self.assertRaises((ValueError,RuntimeError)):
                        channel.ci_baseline()

    def test_sha_first_integration_rejects_fallback_and_candidates(self):
        baseline=channel.ci_baseline()
        actual=channel.ci_baseline_selection(baseline)
        self.assertTrue(actual['source_match'])
        self.assertEqual(actual['profile'],'rd-1.5.3')
        for source,patchset in (('54416dcaa127d209f2cfbdc4b08235bae78ccfe6','v3'),
                                ('51f94394ce61e1f3d26229565c326b2862cbdd1f','v4')):
            with self.subTest(source=source),self.assertRaises(ValueError):
                channel.ci_baseline_selection(dict(baseline,upstream_sha=source,patchset=patchset))
        valid=dict(profile='rd-1.5.3',source_match=True,stable_allowed=True,
                   compatibility_test_only=False,fallback=False)
        with patch.object(channel,'require_selection',return_value=valid) as select:
            self.assertEqual(channel.ci_baseline_selection(baseline),valid)
        select.assert_called_once_with('1.5.3','v3',channel='ci',source_sha=REVIEWED_SHA)
        for changes in (dict(source_match=False),dict(fallback=True),
                        dict(stable_allowed=False),dict(compatibility_test_only=True)):
            with self.subTest(changes=changes),patch.object(channel,'require_selection',return_value=dict(valid,**changes)):
                with self.assertRaises(ValueError):
                    channel.ci_baseline_selection(baseline)

    def test_workflow_upstream_monitor_stays_explicit_and_is_not_suppressed(self):
        root=Path(__file__).resolve().parents[2]
        monitor=(root/'.github/workflows/upstream-main-compatibility.yml').read_text()
        ci=(root/'.github/workflows/ci.yml').read_text()
        self.assertIn('schedule:',monitor)
        self.assertIn('scripts/release/channel.py resolve --channel ci --ref "$UPSTREAM_SHA"',monitor)
        self.assertIn('uses: ./.github/workflows/compat-check.yml',monitor)
        self.assertIn('scripts/release/channel.py resolve --channel "$CHANNEL" --ref "$REQUESTED_REF"',ci)
        self.assertNotIn('continue-on-error: true',monitor)
        self.assertIn('ci-upstream-baseline.json',ci)


if __name__=='__main__':
    unittest.main()
