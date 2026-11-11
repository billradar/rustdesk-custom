"""Report-attempt selection must not mix stale failures or lose prior successes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.release import artifacts

ROOT=Path(__file__).resolve().parents[2]


class ArtifactTests(unittest.TestCase):
    def test_latest_attempt_legacy_fallback_and_bounds(self):
        base='report-123'
        rows=[{'name':base},{'name':base+'-attempt-1'},{'name':base+'-attempt-2'},
              {'name':base+'-attempt-999'},{'name':base+'-attempt-3','expired':True},
              {'name':base+'4-attempt-2'}]
        self.assertEqual(artifacts.select_name(rows,base,2),base+'-attempt-2')
        self.assertEqual(artifacts.select_name(rows,base,1),base+'-attempt-1')
        self.assertEqual(artifacts.select_name(rows[:1],base,2),base)
        self.assertEqual(artifacts.select_name(rows[1:2],base,2),base+'-attempt-1')
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            artifacts.select_name(rows+[{'name':base+'-attempt-2'}],base,2)

    def test_partial_rerun_discards_old_failure_but_reuses_untouched_report(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for name,result in [('preflight-standard-report-123-attempt-1','FAIL'),
                                ('preflight-standard-report-123-attempt-2','PASS'),
                                ('preflight-sos-report-123-attempt-1','PASS')]:
                path=root/name;path.mkdir();(path/'report.json').write_text(json.dumps({'result':result,'artifact':name}))
            reports=artifacts.compatibility_reports(root,'123',2)
            self.assertEqual(len(reports),2)
            self.assertTrue(all(r['result']=='PASS' for r in reports))
            (root/'preflight-standard-report-123-attempt-2/report.json').write_text('broken')
            with self.assertRaises(ValueError):artifacts.compatibility_reports(root,'123',2)

    def test_download_is_bound_to_run_and_selects_exact_name(self):
        run={'id':123,'run_attempt':2,'repository':{'full_name':'owner/repo'}}
        rows={'artifacts':[{'name':'discovery-123-attempt-1'},{'name':'discovery-123-attempt-2'}]}
        with tempfile.TemporaryDirectory() as td,patch.object(artifacts,'api',side_effect=[run,rows]),patch.object(artifacts.subprocess,'run') as download:
            name=artifacts.download('owner/repo','123','discovery-123',Path(td))
            self.assertEqual(name,'discovery-123-attempt-2')
            self.assertIn(name,download.call_args.args[0])
        with tempfile.TemporaryDirectory() as td,patch.object(artifacts,'api',return_value=dict(run,id=999)),patch.object(artifacts.subprocess,'run') as download:
            with self.assertRaisesRegex(ValueError,'mismatch'):
                artifacts.download('owner/repo','123','discovery-123',Path(td))
            download.assert_not_called()

    def test_rerunnable_reports_have_attempts_but_payload_names_are_unchanged(self):
        prefixes=('platform-aggregate-','channel-discovery-','patchset-selection-',
                  'preflight-','flutter-','generation-compatibility-','nightly-discovery-',
                  'nightly-qualification-','release-preflight-','upstream-main-','nightly-route-')
        checked=0
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            workflow=yaml.safe_load(path.read_text())
            for job in workflow['jobs'].values():
                for step in job.get('steps',[]):
                    if not step.get('uses','').startswith('actions/upload-artifact@'):continue
                    name=step.get('with',{}).get('name','')
                    if name.startswith(prefixes):
                        self.assertIn('github.run_attempt',name);checked+=1
                    if name.startswith(('rustdesk-','android-build-input-','prepared-')):
                        self.assertNotIn('github.run_attempt',name)
        self.assertGreaterEqual(checked,12)


if __name__=='__main__':unittest.main()
