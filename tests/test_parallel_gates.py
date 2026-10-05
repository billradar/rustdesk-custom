"""Dependency invariants: parallel preparation must never bypass client/release gates."""
from pathlib import Path
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]

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
        self.assertEqual(set(jobs['validation-report']['needs']),{'resolve','preflight','bridge','flutter-analyze','windows-helper'})
        for name in ['preflight','bridge','flutter-analyze','windows-helper']:
            self.assertNotIn('continue-on-error',jobs[name])
    def test_clients_and_draft_remain_downstream_of_complete_compatibility(self):
        tag=self.workflow('tag.yml')['jobs']
        self.assertIn('compatibility',tag['prepare']['needs'])
        self.assertIn('compatibility',tag['desktop-build']['needs'])
        self.assertIn('prepare',tag['desktop-build']['needs'])
        self.assertIn('compatibility',tag['android-build']['needs'])
        self.assertIn('prepare',tag['android-build']['needs'])
        self.assertIn('android-build',tag['android-sign']['needs'])
        self.assertIn('desktop-build',tag['draft']['needs'])
        self.assertIn('android-build',tag['draft']['needs'])
        core=self.workflow('build.yml')['jobs']
        self.assertEqual(core['validate']['needs'],'build')
        self.assertTrue(any(s.get('name')=='Verify shared helper provenance and digest' for s in core['build']['steps']))
        self.assertFalse(any(s.get('name')=='Build official WindowInjection helper' for s in core['build']['steps']))

if __name__=='__main__':unittest.main()
