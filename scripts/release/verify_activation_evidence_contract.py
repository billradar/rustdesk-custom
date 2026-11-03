"""Offline mocked API tests for the real-evidence verifier."""
from copy import deepcopy
import unittest
from scripts.release.verify_activation_evidence import verify

SHA = '3b116171ac7e6a68c01cf59dbf1aaa738f57d4d0'
HEADS = {
    '7e235a579e04f8648a37bed55dfb135df458b30248936a4519f2ef1e6c014738': '1962da0a2e25fa4d48509d10f3ee87cccd9e11dc',
    'a4bbba02e3e23edc9cd27f97ede5a1239f540c4ca448fa51d2ced98ea0ef7a75': 'e9f1124e3a05d199103b37453fad1ef874ab1bbe',
}
RUNS = [(41639117979, 'Patchset content version contract'),
        (41639117965, 'CI - Patch and Build compatibility'),
        (41639117724, 'Coordinator cutover offline contracts')]
RELEASES = [432254527, 431170313, 430489827]


def fixture():
    evidence = dict(main_sha=SHA, successful_run_ids=[i for i, _ in RUNS],
                    journal_heads=HEADS.copy(), release_ids=RELEASES[:])
    api = {'git/ref/heads/main': {'ref': 'refs/heads/main', 'object': {'sha': SHA}},
           'git/matching-refs/heads/release-coordinator/v1/': [
               {'ref': 'refs/heads/release-coordinator/v1/nightly/' + k,
                'object': {'type': 'commit', 'sha': v}} for k, v in HEADS.items()],
           'releases?per_page=100': [{'id': i} for i in RELEASES]}
    for i, name in RUNS:
        api['actions/runs/' + str(i)] = dict(id=i, name=name, head_sha=SHA,
            status='completed', conclusion='success', event='push',
            repository={'full_name': 'billradar/rustdesk-custom'})
    for i in RELEASES:
        api['releases/' + str(i)] = dict(id=i, draft=True, published_at=None,
                                        assets=[{'id': j} for j in range(32)])
    for status in ('in_progress', 'queued', 'waiting'):
        api['actions/runs?status=' + status + '&per_page=100'] = {'total_count': 0, 'workflow_runs': []}
    return evidence, api


class EvidenceContract(unittest.TestCase):
    def test_verified_evidence_is_not_activation(self):
        evidence, api = fixture()
        self.assertEqual(verify(evidence, lambda p: api[p])['decision'],
                         'EVIDENCE_VERIFIED_NOT_ACTIVATED')

    def test_fail_closed_on_remote_drift(self):
        for path, mutate in (
            ('git/ref/heads/main', lambda x: x['object'].update(sha='a'*40)),
            ('actions/runs/41639117979', lambda x: x.update(conclusion='failure')),
            ('actions/runs/41639117979', lambda x: x.update(head_sha='b'*40)),
            ('actions/runs/41639117979', lambda x: x.update(repository={'full_name': 'other/repo'})),
            ('git/matching-refs/heads/release-coordinator/v1/', lambda x: x.pop()),
            ('releases/432254527', lambda x: x.update(draft=False)),
            ('actions/runs?status=queued&per_page=100', lambda x: x.update(total_count=1, workflow_runs=[{'id': 999}])),
        ):
            with self.subTest(path=path):
                evidence, api = fixture()
                mutate(api[path])
                with self.assertRaisesRegex(ValueError, 'ACTIVATION_EVIDENCE_INVALID'):
                    verify(evidence, lambda p: api[p])

    def test_excludes_only_own_evidence_workflow(self):
        evidence, api = fixture()
        api['actions/runs?status=in_progress&per_page=100'] = {
            'total_count': 1, 'workflow_runs': [{'id': 123}]}
        self.assertEqual(verify(evidence, lambda p: api[p], own_run_id=123)['decision'],
                         'EVIDENCE_VERIFIED_NOT_ACTIVATED')
        with self.assertRaisesRegex(ValueError, 'not quiescent'):
            verify(evidence, lambda p: api[p], own_run_id=124)

    def test_missing_remote_evidence_fails_closed(self):
        evidence, api = fixture()
        del api['actions/runs/41639117979']
        with self.assertRaises(KeyError):
            verify(evidence, lambda p: api[p])

    def test_rejects_extra_unreviewed_fields(self):
        evidence, api = fixture()
        evidence['decision'] = 'GO'
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            verify(evidence, lambda p: api[p])


if __name__ == '__main__':
    unittest.main()
