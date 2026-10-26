#!/usr/bin/env python3
import os,unittest
from unittest.mock import patch
from scripts.release import stable_router as router

class RouterContract(unittest.TestCase):
    def test_attempts(self):
        row=dict(display_title='Stable v1.5.1 / draft',head_sha='a'*40,head_branch='main',event='workflow_dispatch',status='completed',conclusion='success')
        s=lambda rows:router.state(rows,'v1.5.1','a'*40)
        self.assertEqual(s([]),'RETRY')
        self.assertEqual(s([row]),'RETRY')
        self.assertEqual(s([row]*3),'EXHAUSTED')
        self.assertEqual(s([dict(row,status='queued')]),'ACTIVE')
        self.assertEqual(s([dict(row,head_sha='b'*40)]),'RETRY')
        self.assertEqual(s([dict(row,display_title='Stable v1.5.1 / release')]),'RETRY')
    def test_untrusted_context(self):
        with patch.dict(os.environ,dict(GITHUB_REPOSITORY=router.REPO,GITHUB_REF='refs/heads/development',GITHUB_EVENT_NAME='schedule',GITHUB_SHA='a'*40)),patch.object(router,'choose_stable') as choose:
            with self.assertRaises(ValueError):router.route()
            choose.assert_not_called()
    def test_existing_incomplete_fails_closed(self):
        release=dict(version='1.5.1',upstream_sha='b'*40)
        with patch.object(router,'patchset_for_version',return_value='v2'),patch.object(router,'patch_hash',return_value='d'*64):
            identity=router.build_identity('b'*40,'v2','d'*64,'d'*64)
            row=dict(body='Build Identity: '+identity+'\nUpstream SHA: '+'b'*40+'\nAutomation-State: complete',prerelease=False,assets=[dict(name='SHA256SUMS',state='uploaded')])
            with patch.object(router,'release_rows',return_value=[row]):
                self.assertTrue(router.existing(release))
            with patch.object(router,'release_rows',return_value=[dict(row,assets=[])]):
                with self.assertRaises(ValueError):router.existing(release)
if __name__=='__main__':unittest.main()
