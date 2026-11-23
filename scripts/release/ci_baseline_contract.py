"""CI source routing: repository regression baseline vs explicit moving upstream check."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import channel

REVIEWED_SHA='54416dcaa127d209f2cfbdc4b08235bae78ccfe6'


class CiBaselineTests(unittest.TestCase):
    def test_reviewed_baseline_matches_previous_successful_compatibility_run(self):
        value=channel.ci_baseline()
        self.assertEqual(value['upstream_sha'],REVIEWED_SHA)
        self.assertEqual(value['upstream_version'],'1.5.3')
        self.assertEqual(value['patchset'],'v3')
        self.assertEqual(value['evidence_run_id'],44107538838)

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
            dict(original,evidence_run_id=0),
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
