"""Manually reconcile exactly one indexed historical Worker; no dispatch or release."""
import argparse
from scripts.release.coordinator.runtime import context, index_record, clock
from scripts.release.coordinator.store import GitHubAPI, GitRefStore
from scripts.release.coordinator.reconcile import Reconciler, ActionsEvidence
from scripts.release.coordinator.transitions import provenance

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-id', required=True, type=int)
    p.add_argument('--expected-journal-sha', required=True)
    p.add_argument('--expected-identity', required=True)
    args = p.parse_args()
    repo = context('release-coordinator-manual-reconcile.yml', ('workflow_dispatch',))
    if args.run_id <= 0 or len(args.expected_journal_sha) != 40 or len(args.expected_identity) != 64:
        raise ValueError('Invalid exact-match input')
    api = GitHubAPI()
    indexed = index_record(api, repo, args.run_id)
    if indexed is None or indexed.workflow_run_id != str(args.run_id) or indexed.build_identity != args.expected_identity:
        raise ValueError('No matching authenticated run index')
    journal = GitRefStore(api, repo, indexed.channel, indexed.build_identity)
    snapshot = journal.load()
    if snapshot is None or snapshot.sha != args.expected_journal_sha:
        raise ValueError('Journal head changed; fresh review required')
    record = snapshot.record
    if (record.workflow_run_id != str(args.run_id) or record.build_identity != indexed.build_identity
            or record.reservation_id != indexed.reservation_id or record.fence != indexed.fence):
        raise ValueError('Run index / journal fence mismatch')
    if provenance(record).get('worker', {}).get('workflow_run_id') != str(args.run_id):
        raise ValueError('Worker provenance mismatch')
    result = Reconciler(journal, ActionsEvidence(api, repo)).refresh(snapshot, clock())
    verified = journal.load()
    if verified is None or verified.sha != result.sha:
        raise ValueError('Journal changed after reconciliation')
    print('Verified reconciliation:', args.run_id, verified.record.state.value, verified.record.policy_state.value, verified.sha)

if __name__ == '__main__':
    main()
