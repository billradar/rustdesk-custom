"""Explicit stopped/missing-run recovery; never infer termination from 404."""
from datetime import timedelta
from uuid import uuid4

from .identity import hex_value
from .reconcile import WORKFLOWS
from .store import APIError
from .transitions import recover_missing


RUNS_PAGE_SIZE = 20
MAX_RUN_PAGES = 50  # GitHub filtered Actions inventories are capped at 1,000 runs.


def run_pages(api, repo):
    """Enumerate a complete bounded inventory; never treat truncated evidence as safe."""
    for page in range(1, MAX_RUN_PAGES + 1):
        result = api.request('GET', f'repos/{repo}/actions/runs?branch=main&per_page={RUNS_PAGE_SIZE}&page={page}')
        count = result.get('total_count')
        if type(count) is not int or not 0 <= count < 1000:
            raise ValueError('Filtered Actions inventory may be incomplete')
        rows = result.get('workflow_runs')
        if not isinstance(rows, list) or len(rows) > RUNS_PAGE_SIZE:
            raise ValueError('Invalid Actions run inventory')
        yield rows
        if len(rows) < RUNS_PAGE_SIZE:
            return
    raise ValueError('Incomplete recovery run pagination')


def automatic(api, repo, journal, snapshot, creator, now):
    """One policy-authorized recovery of an authenticated missing bound run."""
    from .transitions import auto_recover_missing
    from .runtime import index_record
    try:
        event=auto_recover_missing(snapshot.record,str(uuid4()),str(creator),now,now+timedelta(hours=6))
    except ValueError:
        return None  # Exhausted/terminal/unknown histories remain held.
    if api.request('GET',f'repos/{repo}').get('full_name') != repo:
        raise ValueError('Cannot establish repository access')
    try:
        missing(api,repo,snapshot.record.workflow_run_id)
    except ValueError:
        return None
    for rows in run_pages(api, repo):
        for run in rows:
            if str(run.get('id'))==snapshot.record.workflow_run_id:
                return None  # List and point lookup disagree; no inference.
            if run.get('path','').split('@')[0] != WORKFLOWS[snapshot.record.channel]:
                continue
            if run.get('status') != 'completed':
                indexed=index_record(api,repo,str(run['id']))
                if indexed is None or indexed.build_identity==snapshot.record.build_identity:
                    return None
    try:
        missing(api,repo,snapshot.record.workflow_run_id)
    except ValueError:
        return None
    return journal.append(event,snapshot)


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
    for rows in run_pages(api, repo):
        for run in rows:
            if run.get('path','').split('@')[0] == WORKFLOWS[snapshot.record.channel]:
                if run.get('status') != 'completed':
                    raise ValueError('Active channel run blocks missing-run recovery')
    missing(api,repo,run_id)
    event=recover_missing(snapshot.record,actor,reason,run_id,str(uuid4()),creator,
                          now,now+timedelta(hours=6))
    # No retries/replays: stale or lost writes require a fresh operator review.
    return journal.append(event,snapshot)
