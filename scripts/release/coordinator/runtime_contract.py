"""Credential-free admission, ambiguous dispatch, stale-worker and wiring tests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch
import yaml

from .contract import NOW, identity
from .model import BuildState
from .runtime import Coordinator, guard, index_record, put_index
from .store import APIError, AmbiguousWrite
from .store_contract import MemoryAPI
from .transitions import grant_retry, finish, reserve_retry
from .retry import Failure

ROOT = Path(__file__).resolve().parents[3]
REPO = 'example/release-test'


class RuntimeAPI(MemoryAPI):
    def __init__(self):
        super().__init__()
        self.dispatches = []
        self.lose_dispatch = False
        self.runs = {}

    def request(self, method, path, data=None):
        if path==f'repos/{REPO}':return {'full_name':REPO}
        if path.startswith(f'repos/{REPO}/actions/runs?'):
            return {'total_count':len(self.runs),'workflow_runs':list(self.runs.values())}
        if '/git/matching-refs/' in path:
            prefix='refs/'+path.split('/git/matching-refs/',1)[1]
            return [dict(ref=ref,object={'sha':sha,'type':'commit'}) for ref,sha in self.refs.items() if ref.startswith(prefix)]
        if '/actions/' in path:
            if method == 'POST' and path.endswith('/dispatches'):
                self.dispatches.append(data)
                if self.lose_dispatch:
                    raise AmbiguousWrite('accepted request, response lost')
                return None
            if '/jobs?' in path:
                return {'jobs':[]}
            key=path.rsplit('/',1)[1]
            if key not in self.runs: raise APIError(404)
            return self.runs[key]
        return super().request(method, path, data)


def run(run_id='123'):
    return dict(id=int(run_id), head_sha='a'*40, run_attempt=1, status='in_progress', conclusion=None,
                repository={'full_name':REPO}, head_repository={'full_name':REPO},
                head_branch='main', event='workflow_dispatch', path='.github/workflows/nightly.yml',
                created_at=NOW.isoformat().replace('+00:00','Z'))


class RuntimeContract(unittest.TestCase):
    def test_production_admission_retires_v1_without_rewriting_history(self):
        from dataclasses import replace
        from .runtime import require_v2_admission
        old = identity('nightly')
        with self.assertRaisesRegex(ValueError, 'LEGACY_IDENTITY_V1_RETIRED'):
            require_v2_admission(old)
        modern = replace(old, policy_version=2, patchset_version='v2.8',
                         build_policy_sha256='a'*64)
        self.assertIsNone(require_v2_admission(modern))
        self.assertNotEqual(old.key, modern.key)

    def test_concurrent_routers_dispatch_once_even_at_same_second(self):
        api = RuntimeAPI()
        c = Coordinator(api, REPO, identity('nightly'))
        snapshot = c.claim(NOW, '99', lambda:'EMPTY')
        barrier = Barrier(2)
        def dispatch(_):
            barrier.wait(timeout=10)
            return c.dispatch(snapshot, dict(release_mode='draft', include_wayland=True), NOW)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(dispatch, [1,2]))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(len(api.dispatches), 1)

    def test_ambiguous_dispatch_is_not_replayed(self):
        api = RuntimeAPI()
        c = Coordinator(api, REPO, identity('nightly'))
        snap = c.claim(NOW, '99', lambda:'EMPTY')
        api.lose_dispatch = True
        with self.assertRaises(AmbiguousWrite):
            c.dispatch(snap, dict(release_mode='draft', include_wayland=True), NOW)
        snap = c.claim(NOW+timedelta(hours=8), '100', lambda:'EMPTY')
        self.assertFalse(c.dispatch(snap, dict(release_mode='draft', include_wayland=True), NOW+timedelta(hours=8)))
        self.assertEqual(len(api.dispatches), 1)
        self.assertEqual(snap.record.attempt, 0)

    def test_concurrent_admissions_bind_only_one_run(self):
        api = RuntimeAPI()
        c = Coordinator(api, REPO, identity('nightly'))
        snap = c.claim(NOW, '99', lambda:'EMPTY')
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda i:c.admit(snap, run(str(i)), NOW), [123,124]))
        self.assertEqual(results.count(True), 1)
        for run_id in (123,124):
            self.assertIsNotNone(index_record(api, REPO, run_id))
        self.assertEqual(c.journal.load().record.attempt, 0)

    def test_manual_retry_claimant_can_bind_its_new_epoch_in_all_modes(self):
        from .transitions import provenance
        for mode in ('dry-run','draft','release'):
            with self.subTest(mode=mode):
                api=RuntimeAPI();c=Coordinator(api,REPO,identity('nightly',release_mode=mode))
                snap=c.claim(NOW,'123',lambda:'EMPTY')
                self.assertTrue(c.admit(snap,run(),NOW))
                old=c.journal.load()
                failed=c.journal.append(finish(old.record,old.record.reservation_id,old.record.fence,
                    NOW,NOW+timedelta(minutes=5),False,Failure.COMPILE.value,'build','fixture'),old)
                granted=c.journal.append(grant_retry(failed.record,'maintainer','Reviewed fix',NOW+timedelta(minutes=10)),failed)
                api.runs['123']=dict(run(),status='completed',conclusion='failure')
                snap=c.claim(NOW+timedelta(hours=1),'124',lambda:'EMPTY')
                self.assertEqual(provenance(snap.record)['creator'],'124')
                self.assertEqual(snap.record.fence,2)
                self.assertTrue(c.admit(snap,run('124'),NOW+timedelta(hours=1)))
                with self.assertRaises(ValueError): c.admit(snap,api.runs['123'],NOW+timedelta(hours=1))
                with self.assertRaises(ValueError): c.admit(snap,run('123'),NOW+timedelta(hours=1))

    def test_unknown_history_never_bootstraps_reservation(self):
        api = RuntimeAPI()
        c = Coordinator(api, REPO, identity('nightly'))
        with self.assertRaises(ValueError): c.claim(NOW, '99', lambda:'REVIEW')
        self.assertEqual(api.refs,{})
        for state in ('ACTIVE','SUCCESS'):
            self.assertIsNone(c.claim(NOW, '99', lambda:state))

    def test_router_cannot_publish_or_change_configuration(self):
        c = Coordinator(RuntimeAPI(), REPO, identity('nightly'))
        snap = c.claim(NOW, '99', lambda:'EMPTY')
        for values in (dict(release_mode='release', include_wayland=True),
                       dict(release_mode='draft', include_wayland=False),
                       dict(release_mode='draft', include_wayland=True, official_run_id='1')):
            with self.assertRaises(ValueError): c.dispatch(snap, values, NOW)

    def test_worker_guard_rejects_wrong_attempt_source_and_fence(self):
        api = RuntimeAPI()
        c = Coordinator(api, REPO, identity('nightly'))
        snap = c.claim(NOW, '123', lambda:'EMPTY')
        api.runs['123'] = run()
        self.assertTrue(c.admit(snap, run(), NOW))
        env=dict(GITHUB_REPOSITORY=REPO,GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='workflow_dispatch',
                 GITHUB_WORKFLOW_REF=REPO+'/.github/workflows/nightly.yml@refs/heads/main',
                 GITHUB_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',UPSTREAM_EXPECTED_SHA='a'*40)
        with patch('scripts.release.coordinator.runtime.GitHubAPI',return_value=api),patch.dict(os.environ,env,clear=True):
            guard()
            for changes in (dict(GITHUB_RUN_ATTEMPT='2'),dict(GITHUB_SHA='b'*40),dict(UPSTREAM_EXPECTED_SHA='b'*40)):
                with patch.dict(os.environ,changes),self.assertRaises(ValueError): guard()
            old=c.journal.load()
            ended=c.journal.append(finish(old.record,old.record.reservation_id,old.record.fence,
                NOW,NOW,False,Failure.COMPILE.value,'build','fixture'),old)
            granted=c.journal.append(grant_retry(ended.record,'maintainer','Reviewed fix',NOW),ended)
            c.journal.append(reserve_retry(granted.record,'22222222-2222-4222-8222-222222222222',NOW,NOW+timedelta(hours=6)),granted)
            with self.assertRaises(ValueError): guard()

    def test_admission_denials_cannot_run_under_another_worker_index(self):
        api=RuntimeAPI();c=Coordinator(api,REPO,identity('nightly'))
        snap=c.claim(NOW,'123',lambda:'EMPTY')
        self.assertTrue(c.admit(snap,run(),NOW))
        self.assertFalse(c.admit(c.journal.load(),run('124'),NOW))
        self.assertEqual(index_record(api,REPO,'124').workflow_run_id,'123')

    def test_frozen_discovery_tamper_fails_before_any_api_request(self):
        import hashlib, json, tempfile
        from .runtime import admit_nightly
        env=dict(GITHUB_REPOSITORY=REPO,GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='workflow_dispatch',
                 GITHUB_WORKFLOW_REF=REPO+'/.github/workflows/nightly.yml@refs/heads/main',
                 GITHUB_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',RELEASE_MODE='draft')
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'discovery.json'
            path.write_text('{}')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            path.write_text('{"upstream_sha":"tampered"}')
            with patch.dict(os.environ,env,clear=True), patch('scripts.release.coordinator.runtime.GitHubAPI') as api:
                with self.assertRaises(ValueError): admit_nightly(path,digest)
                api.assert_not_called()

    def test_frozen_discovery_drives_actual_admission(self):
        import hashlib, tempfile
        from .runtime import admit_nightly
        api=RuntimeAPI();api.runs['123']=run()
        env=dict(GITHUB_REPOSITORY=REPO,GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='workflow_dispatch',
                 GITHUB_WORKFLOW_REF=REPO+'/.github/workflows/nightly.yml@refs/heads/main',
                 GITHUB_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',RELEASE_MODE='draft')
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'discovery.json';path.write_text('{}')
            with patch.dict(os.environ,env,clear=True), patch('scripts.release.coordinator.runtime.GitHubAPI',return_value=api), \
                 patch('scripts.release.coordinator.runtime.build',return_value=identity('nightly')), \
                 patch('scripts.release.coordinator.runtime.nightly_history',return_value='EMPTY'), \
                 patch('scripts.release.coordinator.runtime.clock',return_value=NOW), \
                 patch('scripts.release.coordinator.runtime.outputs') as out:
                admit_nightly(path,hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertTrue(out.call_args.kwargs['allow'])
                self.assertEqual(index_record(api,REPO,'123').workflow_run_id,'123')

    def test_authenticated_missing_old_run_recovers_without_blocking_a_new_identity(self):
        from dataclasses import replace
        from .runtime import recover_all
        api=RuntimeAPI();old=Coordinator(api,REPO,identity('nightly'))
        snap=old.claim(NOW,'123',lambda:'EMPTY')
        self.assertTrue(old.admit(snap,run(),NOW))
        recover_all(api,REPO,'nightly',NOW+timedelta(hours=1))
        recovered=old.claim(NOW+timedelta(hours=1),'999',lambda:'EMPTY')
        self.assertEqual(recovered.record.policy_state.value,'READY')
        self.assertEqual((recovered.record.workflow_run_id,recovered.record.fence,recovered.record.attempt),('',2,0))
        from .transitions import provenance
        self.assertEqual(provenance(recovered.record)['missing_run_uncertain_attempts'],1)
        self.assertTrue(old.dispatch(recovered,{'release_mode':'draft','include_wayland':True},NOW+timedelta(hours=1)))
        again=old.claim(NOW+timedelta(hours=1),'1000',lambda:'EMPTY')
        self.assertFalse(old.dispatch(again,{'release_mode':'draft','include_wayland':True},NOW+timedelta(hours=1)))
        self.assertEqual(len(api.dispatches),1)
        changed=replace(identity('nightly'),source=replace(identity('nightly').source,upstream_sha='b'*40))
        fresh=Coordinator(api,REPO,changed).claim(NOW+timedelta(hours=1),'999',lambda:'EMPTY')
        self.assertNotEqual(fresh.record.build_identity,snap.record.build_identity)

    def test_wrong_writer_context_is_rejected_without_credentials(self):
        from .runtime import context
        with patch.dict(os.environ,dict(GITHUB_REPOSITORY=REPO,GITHUB_REF='refs/pull/1/merge',
                        GITHUB_EVENT_NAME='pull_request',GITHUB_WORKFLOW_REF=REPO+'/.github/workflows/nightly.yml@refs/heads/main'),clear=True):
            with self.assertRaises(ValueError): context('nightly.yml',('workflow_dispatch',))

    def test_nightly_permission_and_admission_boundary(self):
        w=yaml.safe_load((ROOT/'.github/workflows/nightly.yml').read_text())
        self.assertEqual(w['permissions'],{'contents':'read','actions':'read'})
        writes={n for n,j in w['jobs'].items() if j.get('permissions',{}).get('contents')=='write'}
        self.assertEqual(writes,{'draft','coordinator-admit'})
        admit=w['jobs']['coordinator-admit']
        self.assertEqual(admit['permissions'],{'contents':'write','actions':'read'})
        self.assertIn("github.ref == 'refs/heads/main'",admit['if'])
        self.assertIn('github.workflow_ref',admit['if'])
        self.assertNotIn('secrets',str(admit))
        self.assertNotIn('environment',admit)
        self.assertIn('needs.coordinator-admit.outputs.allow',w['jobs']['prepare']['if'])
        self.assertEqual(set(w['on']['workflow_dispatch']['inputs']),{'release_mode','include_wayland'})
        self.assertIn('discovery_sha256',w['jobs']['resolve']['outputs'])
        self.assertNotIn('RELEASE_COORDINATOR_ENABLED',w.get('env',{}))
        dedup=next(x for x in w['jobs']['resolve']['steps'] if x.get('id')=='dedup')
        self.assertEqual(dedup['env']['RELEASE_COORDINATOR_ENABLED'],'true')

    def test_readonly_guards_precede_privileged_and_compile_work(self):
        for file in ('nightly.yml','build-platform.yml','build-stable-windows.yml','build-wayland-target.yml','prepare-source.yml'):
            w=yaml.safe_load((ROOT/'.github/workflows'/file).read_text())
            for name,j in w['jobs'].items():
                steps=j.get('steps',[])
                compile_at=[i for i,s in enumerate(steps) if s.get('name') in (
                    'Official-compatible compile, package and independent gates','Build and verify selected variant')
                    or s.get('uses')=='./.github/actions/android-yubikey-sign'
                    or 'nightly.py aggregate' in s.get('run','') or 'nightly.py draft' in s.get('run','')]
                for index in compile_at:
                    guards=[i for i,s in enumerate(steps[:index]) if 'coordinator.runtime guard' in s.get('run','')]
                    self.assertTrue(guards,(file,name))
                    for i in guards:
                        self.assertEqual(steps[i]['env'],{'GH_TOKEN':'${{ github.token }}'})
        maintenance=yaml.safe_load((ROOT/'.github/workflows/release-coordinator.yml').read_text())
        self.assertEqual(maintenance['permissions'],{'contents':'read','actions':'read'})
        self.assertNotIn('secrets',str(maintenance))
        self.assertNotIn('environment',maintenance['jobs']['coordinator-state'])


if __name__=='__main__':
    unittest.main()
