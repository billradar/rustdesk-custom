"""Credential-free server-protection probe and workflow boundary contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

from .integration import REPOSITORY, trusted_context
from .protection import (BRANCH, WORKFLOW, INDEX, RULES, Canaries,
                         protection_exercise, verify_rules)
from .store import APIError
from .store_contract import MemoryAPI

ROOT = Path(__file__).resolve().parents[3]


class ProtectedAPI(MemoryAPI):
    def __init__(self):
        super().__init__()
        self.policies = {i: dict(name=n, target='branch', enforcement='active', bypass_actors=[],
            conditions={'ref_name': {'include': inc, 'exclude': []}},
            rules=[{'type': k} for k in sorted(kinds)]) for i, (n, inc, kinds) in RULES.items()}
        self.status = 422
        self.negative_calls = 0

    def request(self, method, path, data=None):
        if '/rulesets/' in path:
            return copy.deepcopy(self.policies[int(path.rsplit('/', 1)[1])])
        suffix = path.split('/git/', 1)[1]
        if ((method == 'DELETE' and suffix.startswith('refs/'))
                or (method == 'PATCH' and (suffix.startswith('refs/heads/'+INDEX+'/')
                                          or data.get('force') is True))):
            self.negative_calls += 1
            raise APIError(self.status)
        return super().request(method, path, data)


class ProtectionContract(unittest.TestCase):
    def test_exact_harness_positive_controls_and_server_rejections(self):
        api = ProtectedAPI()
        result = protection_exercise(api, 'example/test', 'offline')
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(len(result['positive_controls']), 3)
        self.assertEqual(len(result['rejections']), 5)
        self.assertEqual(api.negative_calls, 5)
        self.assertEqual(len(result['protected_storage']['checks']), 7)
        self.assertEqual(len(result['refs']), 5)
        self.assertEqual(set(api.refs), set(result['refs']))

    def test_low_permission_bypass_visibility_is_reported_without_claiming_empty(self):
        api = ProtectedAPI()
        for row in api.policies.values():
            del row['bypass_actors']
        result = protection_exercise(api, 'example/test', 'offline')
        self.assertEqual(set(result['bypass_visibility'].values()), {'not_exposed_to_token'})
        self.assertEqual(len(result['rejections']), 5)

    def test_rule_drift_stops_before_any_state_write(self):
        changes = [dict(enforcement='disabled'), dict(bypass_actors=[{'actor_id': 1}]),
                   dict(rules=[{'type':'deletion'}]), dict(conditions={'ref_name':{'include':['~ALL'],'exclude':[]}}),
                   dict(rules=[{'type': k, 'parameters': {'update_allows_fetch_and_merge':True}}
                               for k in ('deletion','non_fast_forward','update')])]
        for change in changes:
            api = ProtectedAPI();api.policies[26375414].update(change)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                protection_exercise(api, 'example/test', 'offline')
            self.assertEqual(api.refs, {});self.assertEqual(api.objects, {})

    def test_auth_rate_limit_and_outage_are_never_protection_pass(self):
        for status in (401, 403, 429, 500, 503):
            api = ProtectedAPI();api.status = status
            with self.subTest(status=status), self.assertRaises(AssertionError):
                protection_exercise(api, 'example/test', 'offline')
            self.assertEqual(api.negative_calls, 1)

    def test_successful_forbidden_write_is_failure(self):
        class Unprotected(ProtectedAPI):
            def request(self, method, path, data=None):
                if method == 'PATCH' and data.get('force') is True:
                    self.refs['refs/'+path.split('/git/refs/',1)[1]] = data['sha']
                    return {}
                return super().request(method, path, data)
        with self.assertRaisesRegex(AssertionError, 'accepted forbidden'):
            protection_exercise(Unprotected(), 'example/test', 'offline')

    def test_existing_index_not_adopted_and_no_delete_outside_owned_refs(self):
        api = ProtectedAPI()
        journal = 'heads/coordinator-integration/v1/stable/'+'a'*64
        index = 'heads/'+INDEX+'/'+'b'*64
        probe = Canaries(api, 'example/test', journal, 'c'*40, 'd'*40, index)
        api.refs['refs/'+index] = 'c'*40
        with self.assertRaises(ValueError):probe.create_index()
        for ref in (journal, index, 'heads/main', 'tags/test'):
            with self.subTest(ref=ref), self.assertRaises(AssertionError):probe.reject('x', ref, 'DELETE')
        self.assertEqual(api.negative_calls, 0)
        with self.assertRaises(AssertionError):
            Canaries(api, 'example/test', 'heads/main', 'c'*40, 'd'*40, index)

    def test_trusted_context_uses_exact_new_workflow_and_branch(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'event.json'
            path.write_text(json.dumps(dict(number=175, pull_request=dict(
                head=dict(ref=BRANCH, repo={'full_name':REPOSITORY}), base=dict(repo={'full_name':REPOSITORY})))))
            env = dict(GITHUB_REPOSITORY=REPOSITORY, COORDINATOR_INTEGRATION_ALLOW_WRITE='true',
                GITHUB_RUN_ID='1', GITHUB_EVENT_NAME='pull_request', GITHUB_EVENT_PATH=str(path),
                GITHUB_HEAD_REF=BRANCH, GITHUB_REF='refs/pull/175/merge',
                GITHUB_WORKFLOW_REF=REPOSITORY+'/'+WORKFLOW+'@refs/pull/175/merge')
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(trusted_context(branch=BRANCH, workflow_path=WORKFLOW), REPOSITORY)
                with self.assertRaises(ValueError):trusted_context()
                for change in ({'GITHUB_EVENT_NAME':'pull_request_target'}, {'GITHUB_HEAD_REF':'foreign'},
                               {'GITHUB_REPOSITORY':'fork/repo'}, {'COORDINATOR_INTEGRATION_ALLOW_WRITE':'false'}):
                    with patch.dict(os.environ, change), self.assertRaises(ValueError):
                        trusted_context(branch=BRANCH, workflow_path=WORKFLOW)

    def test_workflow_is_isolated_without_secrets_signing_or_dispatch(self):
        text = (ROOT/WORKFLOW).read_text();w = yaml.safe_load(text)
        self.assertEqual(set(w['on']), {'pull_request','workflow_dispatch'})
        self.assertEqual(w['permissions'], {'contents':'read'})
        self.assertEqual(set(w['jobs']), {'isolated-state-writer'})
        job = w['jobs']['isolated-state-writer']
        self.assertEqual(job['permissions'], {'contents':'write'})
        self.assertEqual(job['runs-on'], 'ubuntu-22.04')
        self.assertIs(job['steps'][0]['with']['persist-credentials'], False)
        self.assertIn(BRANCH, job['if'])
        self.assertIn('head.repo.full_name == github.repository', job['if'])
        self.assertIn('refs/heads/main', job['if'])
        for token in ('secrets.', 'environment:', 'actions: write', 'pull_request_target', 'release-coordinator/v1/'):
            self.assertNotIn(token, text)
        writer = next(s for s in job['steps'] if s.get('run'))
        self.assertEqual(writer['run'], 'python3 -m scripts.release.coordinator.protection')
        self.assertEqual(set(writer['env']), {'GH_TOKEN','COORDINATOR_INTEGRATION_ALLOW_WRITE'})
        self.assertNotIn('env', job)


if __name__ == '__main__':
    unittest.main()
