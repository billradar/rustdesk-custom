"""Stable source, lock, purpose upgrade and safety wiring; no credentials."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from scripts.release import stable_lock
from .contract import NOW, identity
from .model import BuildState
from .runtime import Coordinator, admit_stable, build, guard, index_record, route_stable, stable_history
from .runtime_contract import RuntimeAPI, REPO, ROOT, run
from .transitions import finish, grant_upgrade, provenance, reserve_upgrade

TOKEN = '22222222-2222-4222-8222-222222222222'
DATA = dict(channel='stable', upstream_sha='a'*40, version='1.5.1', upstream_tag='v1.5.1', upstream_ref='v1.5.1', patchset='v2')


def stable_run(n='123'):
    return dict(run(n), path='.github/workflows/tag.yml')


def env(included=True):
    return dict(GITHUB_REPOSITORY=REPO, GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='workflow_dispatch',
                GITHUB_WORKFLOW_REF=REPO+'/.github/workflows/tag.yml@refs/heads/main',
                GITHUB_SHA='a'*40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', RELEASE_MODE='draft',
                INCLUDE_WAYLAND=str(included).lower(), ANDROID_PRODUCTION_SIGNING_ENABLED='false')


class StableRuntimeContract(unittest.TestCase):
    def successful_dry_run(self):
        api=RuntimeAPI();c=Coordinator(api,REPO,identity('stable',release_mode='dry-run'))
        s=c.claim(NOW,'123',lambda:'EMPTY');self.assertTrue(c.admit(s,stable_run(),NOW))
        s=c.journal.load();s=c.journal.append(finish(s.record,s.record.reservation_id,s.record.fence,NOW,
                    NOW+timedelta(minutes=5),True),s)
        api.runs['123']=dict(stable_run(),status='completed',conclusion='success')
        return api,c,s

    def test_actual_lock_admission_and_guard_with_and_without_wayland(self):
        for included in (False,True):
            with self.subTest(included=included),tempfile.TemporaryDirectory() as td,patch.dict(os.environ,env(included),clear=True):
                locked=stable_lock.plan(DATA,'v2');path=Path(td)/'stable-lock.json'
                path.write_text(json.dumps(locked));api=RuntimeAPI();api.runs['123']=stable_run()
                options=dict(STABLE_LOCK_PATH=str(path),STABLE_LOCK_SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             EXPECTED_BUILD_IDENTITY=locked['build_identity'])
                with patch.dict(os.environ,options),patch('scripts.release.coordinator.runtime.GitHubAPI',return_value=api), \
                     patch('scripts.release.coordinator.runtime.clock',return_value=NOW), \
                     patch('scripts.release.coordinator.runtime.stable_history',return_value='EMPTY'), \
                     patch('scripts.release.coordinator.runtime.outputs') as out:
                    admit_stable();self.assertTrue(out.call_args.kwargs['allow']);guard()
                    record=index_record(api,REPO,'123')
                    self.assertEqual(record.build_identity,build(locked,'stable','draft').key)
                    path.write_text('{}')
                    with self.assertRaises(ValueError):admit_stable()
                    with patch.dict(os.environ,GITHUB_RUN_ATTEMPT='2'),self.assertRaises(ValueError):guard()

    def test_foreign_run_cannot_create_a_reservation(self):
        with patch.dict(os.environ,env(),clear=True):
            locked=stable_lock.plan(DATA,'v2');api=RuntimeAPI()
            for wrong in (dict(head_branch='other'),dict(event='pull_request'),dict(repository={'full_name':'evil/fork'}),dict(path='.github/workflows/ci.yml')):
                api.runs['123']=dict(stable_run(),**wrong)
                with patch('scripts.release.stable_lock.current',return_value=locked), \
                     patch('scripts.release.coordinator.runtime.GitHubAPI',return_value=api), self.assertRaises(ValueError):admit_stable()
                self.assertEqual(api.refs,{})

    def test_successful_dry_run_upgrade_is_a_new_fenced_epoch(self):
        api,old,success=self.successful_dry_run()
        production=Coordinator(api,REPO,identity('stable'))
        s=production.claim(NOW+timedelta(hours=1),'124',lambda:'EMPTY')
        self.assertEqual(s.record.build_identity,success.record.build_identity)
        self.assertEqual(s.record.attempt,1);self.assertEqual(s.record.fence,2)
        self.assertNotEqual(s.record.reservation_id,success.record.reservation_id)
        self.assertEqual(provenance(s.record)['purpose'],'draft')
        self.assertEqual(provenance(s.record)['upgraded_from']['result'],'SUCCEEDED')
        self.assertEqual(api.objects[success.sha][0],'commit')
        self.assertTrue(production.admit(s,stable_run('124'),NOW+timedelta(hours=1)))
        current=production.journal.load()
        done=production.journal.append(finish(current.record,current.record.reservation_id,current.record.fence,
                        NOW+timedelta(hours=1),NOW+timedelta(hours=2),True),current)
        self.assertEqual(production.claim(NOW+timedelta(hours=3),'125',lambda:'EMPTY'),done)
        with self.assertRaises(ValueError):finish(done.record,done.record.reservation_id,done.record.fence,
                       done.record.started_at,NOW+timedelta(hours=3),False,'compile','build','late')

    def test_failed_dry_run_grant_can_retry_as_production_without_resetting_attempts(self):
        from .transitions import grant_retry
        from .retry import Failure
        api=RuntimeAPI();dry=Coordinator(api,REPO,identity('stable',release_mode='dry-run'))
        snap=dry.claim(NOW,'123',lambda:'EMPTY');dry.admit(snap,stable_run(),NOW)
        snap=dry.journal.load()
        snap=dry.journal.append(finish(snap.record,snap.record.reservation_id,snap.record.fence,NOW,
                         NOW+timedelta(minutes=5),False,Failure.COMPILE.value,'build','fixture'),snap)
        dry.journal.append(grant_retry(snap.record,'maintainer','Reviewed correction',NOW+timedelta(minutes=10)),snap)
        api.runs['123']=dict(stable_run(),status='completed',conclusion='failure')
        production=Coordinator(api,REPO,identity('stable'))
        snap=production.claim(NOW+timedelta(hours=1),'124',lambda:'EMPTY')
        self.assertEqual(snap.record.attempt,1);self.assertEqual(provenance(snap.record)['purpose'],'draft')
        self.assertTrue(production.admit(snap,stable_run('124'),NOW+timedelta(hours=1)))

    def test_production_mode_retries_keep_authorization_and_publication_gates(self):
        from .transitions import grant_retry, retry_schedule
        from .retry import Failure, RetryPolicy
        for old_mode,new_mode,manual in (('draft','release',True),('release','draft',False)):
            with self.subTest(old=old_mode,new=new_mode,manual=manual):
                api=RuntimeAPI();old=Coordinator(api,REPO,identity('stable',release_mode=old_mode))
                snap=old.claim(NOW,'123',lambda:'EMPTY');old.admit(snap,stable_run(),NOW)
                snap=old.journal.load();completed=NOW+timedelta(minutes=5)
                snap=old.journal.append(finish(snap.record,snap.record.reservation_id,snap.record.fence,NOW,
                      completed,False,(Failure.COMPILE if manual else Failure.SDK).value,'build','fixture'),snap)
                when=NOW+timedelta(minutes=10)
                event=grant_retry(snap.record,'maintainer','Reviewed correction',when) if manual else retry_schedule(
                      snap.record,when,RetryPolicy().next_retry(snap.record,0))
                snap=old.journal.append(event,snap)
                api.runs['123']=dict(stable_run(),status='completed',conclusion='failure')
                new=Coordinator(api,REPO,identity('stable',release_mode=new_mode))
                if not manual:
                    cooling=new.claim(when,'124',lambda:'EMPTY')
                    self.assertEqual(cooling.record.fence,1);self.assertEqual(cooling.record.attempt,1)
                snap=new.claim(NOW+timedelta(hours=8),'124',lambda:'EMPTY')
                self.assertEqual(snap.record.attempt,1);self.assertEqual(provenance(snap.record)['purpose'],new_mode)
                self.assertTrue(new.admit(snap,stable_run('124'),NOW+timedelta(hours=8)))
                with self.assertRaises(ValueError):new.dispatch(snap,dict(release_mode='release',include_wayland=True,upstream_ref='v1.5.1'),when)

    def test_upgrade_budget_and_one_epoch_grant(self):
        _,_,success=self.successful_dry_run();record=replace(success.record,attempt=3);now=NOW+timedelta(hours=1)
        with self.assertRaises(ValueError):reserve_upgrade(record,TOKEN,'draft','124',now,now+timedelta(hours=6))
        granted=grant_upgrade(record,'maintainer','Reviewed additional production attempt',now).after
        upgraded=reserve_upgrade(granted,TOKEN,'draft','124',now,now+timedelta(hours=6)).after
        self.assertEqual(upgraded.attempt,3);self.assertNotIn('upgrade_grant',provenance(upgraded))
        with self.assertRaises(ValueError):reserve_upgrade(upgraded,TOKEN,'draft','125',now,now+timedelta(hours=6))

    def test_pending_purpose_mismatch_cannot_bind_or_write_a_foreign_index(self):
        api=RuntimeAPI();dry=Coordinator(api,REPO,identity('stable',release_mode='dry-run'))
        s=dry.claim(NOW,'123',lambda:'EMPTY');production=Coordinator(api,REPO,identity('stable'))
        with self.assertRaises(ValueError):production.admit(s,dict(stable_run(),head_branch='evil'),NOW)
        self.assertIsNone(index_record(api,REPO,'123'))
        self.assertFalse(production.admit(s,stable_run(),NOW))
        self.assertEqual(production.journal.load(),s)

    def test_stable_dispatch_exact_tag_draft_only(self):
        api=RuntimeAPI();c=Coordinator(api,REPO,identity('stable'),source_provenance=DATA)
        s=c.claim(NOW,'99',lambda:'EMPTY')
        for values in (dict(release_mode='release',include_wayland=True,upstream_ref='v1.5.1'),
                       dict(release_mode='draft',include_wayland=True,upstream_ref='main')):
            with self.assertRaises(ValueError):c.dispatch(s,values,NOW)
        self.assertTrue(c.dispatch(s,dict(release_mode='draft',include_wayland=True,upstream_ref='v1.5.1'),NOW))
        self.assertEqual(api.dispatches,[dict(ref='main',inputs=dict(release_mode='draft',include_wayland=True,upstream_ref='v1.5.1'))])

    def test_latest_stable_version_guard_and_explicit_same_version(self):
        for same in (False,True):
            e=dict(env(),GITHUB_WORKFLOW_REF=REPO+'/.github/workflows/upstream-stable.yml@refs/heads/main',ALLOW_SAME_VERSION=str(same).lower())
            with patch.dict(os.environ,e,clear=True),patch('scripts.release.stable_router.verify_context'), \
                 patch('scripts.release.stable_router.discovery',return_value=DATA), \
                 patch('scripts.release.stable_router.latest_completed_version',return_value='1.5.1'), \
                 patch('scripts.release.stable_router.existing_build',return_value=True) as existing, \
                 patch('scripts.release.coordinator.runtime.GitHubAPI',return_value=RuntimeAPI()), \
                 patch('scripts.release.coordinator.runtime.outputs'):
                route_stable();self.assertEqual(existing.call_count,int(same))

    def test_unknown_or_failed_legacy_history_is_not_a_free_build(self):
        rows=[dict(stable_run(),status='completed',conclusion='failure',display_title='Stable v1.5.1 / draft / wayland=true / android-signing=false')]
        with patch('scripts.release.coordinator.runtime.history',return_value=rows), \
             patch('scripts.release.stable_router.recorded_identity',return_value=identity().historical_digest):
            self.assertEqual(stable_history(RuntimeAPI(),REPO,identity()),'REVIEW')
        with patch('scripts.release.coordinator.runtime.history',return_value=rows), \
             patch('scripts.release.stable_router.recorded_identity',side_effect=ValueError('expired')),self.assertRaises(ValueError):
            stable_history(RuntimeAPI(),REPO,identity())

    def test_two_queued_stable_admissions_create_one_real_reservation(self):
        title='Stable v1.5.1 / draft / wayland=true / android-signing=false'
        first=dict(stable_run('123'),run_number=10,display_title=title)
        later=dict(stable_run('124'),run_number=11,display_title=title,status='queued')
        rows=[later,first];api=RuntimeAPI();api.runs={'123':first,'124':later}
        build_identity=identity('stable');c=Coordinator(api,REPO,build_identity)
        with patch('scripts.release.coordinator.runtime.history',return_value=rows), \
             patch('scripts.release.stable_router.recorded_identity',side_effect=AssertionError('Later lock queried')):
            self.assertEqual(stable_history(api,REPO,build_identity,'123'),'EMPTY')
            snap=c.claim(NOW,'123',lambda:stable_history(api,REPO,build_identity,'123'))
            self.assertTrue(c.admit(snap,first,NOW))
            snap=c.claim(NOW,'124',lambda:self.fail('Managed epoch re-entered legacy history'))
            self.assertFalse(c.admit(snap,later,NOW))
        record=c.journal.load().record
        self.assertEqual(record.workflow_run_id,'123');self.assertEqual(record.attempt,0)
        self.assertEqual(record.state,BuildState.QUEUED)
        self.assertEqual(index_record(api,REPO,'123').workflow_run_id,'123')
        self.assertEqual(index_record(api,REPO,'124').workflow_run_id,'123')

    def test_unindexed_success_without_verified_producer_requires_review(self):
        title='Stable v1.5.1 / draft / wayland=true / android-signing=false'
        old=dict(stable_run('122'),run_number=9,display_title=title,status='completed',conclusion='success')
        current=dict(stable_run(),run_number=10,display_title=title)
        with patch('scripts.release.coordinator.runtime.history',return_value=[current,old]), \
             patch('scripts.release.stable_router.recorded_identity',return_value=identity('stable').historical_digest):
            self.assertEqual(stable_history(RuntimeAPI(),REPO,identity('stable'),'123'),'REVIEW')
        for rows in ([old],[dict(current,run_number=None),old],[current,dict(old,run_number=None)]):
            with patch('scripts.release.coordinator.runtime.history',return_value=rows),self.assertRaises(ValueError):
                stable_history(RuntimeAPI(),REPO,identity('stable'),'123')

    def test_stable_wiring_keeps_publication_and_signing_isolation(self):
        w=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text());jobs=w['jobs']
        self.assertEqual(set(w['on']['workflow_dispatch']['inputs']),{'release_mode','upstream_ref','include_wayland'})
        self.assertIn("needs.coordinator-admit.outputs.allow == 'true'",jobs['prepare']['if'])
        self.assertEqual(jobs['coordinator-admit']['permissions'],{'contents':'write','actions':'read'})
        self.assertNotIn('secrets',jobs['coordinator-admit']);self.assertNotIn('environment',jobs['coordinator-admit'])
        self.assertNotIn('coordinator',str(jobs['publish-existing']))
        signer=jobs['android-sign'];steps=signer['steps']
        guard_at=next(i for i,s in enumerate(steps) if 'coordinator.runtime guard' in s.get('run',''))
        self.assertLess(guard_at,next(i for i,s in enumerate(steps) if s.get('uses')=='./.github/actions/android-yubikey-sign'))
        self.assertIn('scripts/release/coordinator/*',next(s for s in steps if s.get('with',{}).get('sparse-checkout'))['with']['sparse-checkout'])
        for file in ('prepare-source.yml','build-platform.yml','build-stable-windows.yml','build-wayland-target.yml'):
            shared=yaml.safe_load((ROOT/'.github/workflows'/file).read_text())
            guards=[s for j in shared['jobs'].values() for s in j.get('steps',[]) if 'coordinator.runtime guard' in s.get('run','')]
            self.assertTrue(guards,file)
            for s in guards:
                self.assertIn("github.workflow == 'Stable Release Pipeline'",s['if'])
                self.assertIn("github.workflow == 'Nightly Build Pipeline'",s['if'])


if __name__=='__main__':unittest.main()
