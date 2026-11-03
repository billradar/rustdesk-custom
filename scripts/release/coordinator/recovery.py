"""Explicit stopped/missing-run recovery; never infer termination from 404."""
from datetime import timedelta
from uuid import uuid4

from .identity import hex_value
from .reconcile import WORKFLOWS
from .store import APIError
from .transitions import recover_missing


def missing(api, repo, run_id):
    try:
        api.request('GET',f'repos/{repo}/actions/runs/{run_id}')
    except APIError as error:
        if error.status==404:
            return
        raise
    raise ValueError('Old run exists; use normal reconciliation')


def recover(api, repo, journal, expected_sha, run_id, confirmation, actor, reason, creator, now):
    hex_value(expected_sha,40)
    if confirmation != 'STOPPED_AND_BUILD_STARTED':
        raise ValueError('Explicit stopped-run and actual-build-entry attestation required')
    snapshot=journal.load()
    if snapshot is None or snapshot.sha != expected_sha or snapshot.record.workflow_run_id != run_id:
        raise ValueError('Recovery snapshot/run changed; review current reservation')
    if api.request('GET',f'repos/{repo}').get('full_name') != repo:
        raise ValueError('Cannot establish repository access')
    missing(api,repo,run_id)
    # Enumerate repository runs, not only one status or the first page. Any
    # active run of this channel blocks operator retirement of the old epoch.
    for page in range(1,101):
        rows=api.request('GET',f'repos/{repo}/actions/runs?branch=main&per_page=100&page={page}')['workflow_runs']
        for run in rows:
            if run.get('path','').split('@')[0] == WORKFLOWS[snapshot.record.channel]:
                if run.get('status') != 'completed':
                    raise ValueError('Active channel run blocks missing-run recovery')
        if len(rows)<100:
            break
    else:
        raise ValueError('Incomplete recovery run pagination')
    missing(api,repo,run_id)
    event=recover_missing(snapshot.record,actor,reason,run_id,str(uuid4()),creator,
                          now,now+timedelta(hours=6))
    # No retries/replays: stale or lost writes require a fresh operator review.
    return journal.append(event,snapshot)
