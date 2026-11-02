"""Trusted-main coordinator entrypoints. No signing or publication interfaces."""
import argparse
from base64 import b64decode
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from .identity import BuildIdentity, SourceIdentity, canonical, hex_value
from .model import BuildState, PolicyState, Record, ReservationState, reserve
from .reconcile import ActionsEvidence, Reconciler, WORKFLOWS, log_decision
from .store import APIError, AmbiguousWrite, Conflict, GitHubAPI, GitRefStore, decode_record, parse_time, timestamp
from .transitions import bind_verified, dispatch_intent, grant_retry, grant_upgrade, provenance, reserve_retry, reserve_upgrade

INDEX = 'heads/release-coordinator-runs/v1/'


def clock():
    return datetime.now(timezone.utc).replace(microsecond=0)


def repository():
    repo = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid workflow repository')
    return repo


def context(file, events):
    repo = repository()
    if (os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') not in events
            or os.environ.get('GITHUB_WORKFLOW_REF') != f'{repo}/.github/workflows/{file}@refs/heads/main'):
        raise ValueError('Coordinator requires the exact trusted-main workflow')
    return repo


def flag(name):
    value = os.environ.get(name, 'false')
    if value not in ('true', 'false'):
        raise ValueError('Invalid frozen option: ' + name)
    return value == 'true'


def outputs(**data):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            for key, value in data.items():
                value = str(value).lower() if isinstance(value, bool) else str(value)
                if '\n' in value or '\r' in value:
                    raise ValueError('Unsafe coordinator output')
                stream.write(f'{key}={value}\n')
    print(json.dumps(data, sort_keys=True))


def build(data, channel, mode):
    from scripts.upstream.patchsets import patch_hash, patchset_for_version, verify
    from scripts.platform.wayland import POLICY
    patchset = data['patchset']
    if patchset != patchset_for_version(data.get('upstream_version') or data.get('version', '')):
        raise ValueError('Patchset/source version mismatch')
    verify(patchset)
    common, sos = patch_hash('common', patchset), patch_hash('sos', patchset)
    if data.get('common_patch_hash') != common or data.get('sos_patch_hash') != sos:
        raise ValueError('Discovery patch hashes changed')
    wayland, signing = flag('INCLUDE_WAYLAND'), flag('ANDROID_PRODUCTION_SIGNING_ENABLED')
    policy = hashlib.sha256(POLICY.read_bytes()).hexdigest() if wayland else ''
    if data.get('wayland_policy_sha256', '') != policy:
        raise ValueError('Frozen Wayland policy mismatch')
    result = BuildIdentity(channel, SourceIdentity(data['upstream_sha'], patchset, common, sos),
                           wayland, policy, signing, mode)
    if channel == 'stable':
        result.verify_historical(data['build_identity'])
    return result


def index_record(api, repo, run_id):
    if not re.fullmatch('[1-9][0-9]*', str(run_id)):
        raise ValueError('Invalid index run ID')
    base = f'repos/{repo}/git/'
    try:
        ref = api.request('GET', base + 'ref/' + INDEX + str(run_id))
    except APIError as error:
        if error.status == 404:
            return None
        raise
    if ref.get('ref') != 'refs/' + INDEX + str(run_id) or ref['object'].get('type') != 'commit':
        raise ValueError('Invalid run index ref')
    sha = ref['object']['sha']
    hex_value(sha, 40)
    commit = api.request('GET', base + 'commits/' + sha)
    tree = api.request('GET', base + 'trees/' + commit['tree']['sha'])
    entries = [e for e in tree['tree'] if e['path'] == 'state.json' and e['mode'] == '100644' and e['type'] == 'blob']
    if tree.get('truncated') or len(entries) != 1:
        raise ValueError('Run index has no canonical state')
    blob = api.request('GET', base + 'blobs/' + entries[0]['sha'])
    if blob.get('encoding') != 'base64':
        raise ValueError('Invalid run index encoding')
    raw = b64decode(''.join(blob['content'].split()), validate=True)
    if len(raw) > 65536 or canonical(json.loads(raw)) != raw:
        raise ValueError('Invalid run index state')
    record = decode_record(json.loads(raw))
    document = dict(provenance(record)['build'])
    document['source'] = SourceIdentity(**document['source'])
    identity = BuildIdentity(**document)
    if identity.key != record.build_identity or identity.source.upstream_sha != record.upstream_sha:
        raise ValueError('Run index identity mismatch')
    return record


def put_index(api, repo, run_id, snapshot):
    """Immutable evidence pointer, never a replacement for the identity lock."""
    path = f'repos/{repo}/git/'
    try:
        api.request('POST', path + 'refs', {'ref': 'refs/' + INDEX + str(run_id), 'sha': snapshot.sha})
    except (APIError, AmbiguousWrite):
        pass  # Read back even an apparently successful write before admission.
    actual = index_record(api, repo, run_id)
    expected = snapshot.record
    if actual is None or (actual.build_identity, actual.reservation_id, actual.fence, actual.workflow_run_id) != (
            expected.build_identity, expected.reservation_id, expected.fence, expected.workflow_run_id):
        raise AmbiguousWrite('Run index outcome requires review')


class Coordinator:
    def __init__(self, api, repo, identity, *, evidence=None, source_provenance=None):
        self.api, self.repo, self.identity = api, repo, identity
        keys = ('official_run_id', 'official_run_url', 'upstream_repository', 'upstream_ref',
                'upstream_tag', 'upstream_version', 'version')
        self.source_provenance = {k:v for k,v in (source_provenance or {}).items() if k in keys and isinstance(v,str)}
        self.journal = GitRefStore(api, repo, identity.channel, identity.key)
        self.evidence = evidence or ActionsEvidence(api, repo)

    def claim(self, now, creator, legacy_check):
        """Read/qualify/reserve, with CAS retries only after a fresh decision."""
        for _ in range(4):
            snapshot = self.journal.load()
            try:
                if snapshot is None:
                    decision = legacy_check()
                    if decision in ('ACTIVE', 'SUCCESS'):
                        return None
                    if decision != 'EMPTY':
                        raise ValueError('Historical identity/failure requires review')
                    data = dict(build=asdict(self.identity), source=self.source_provenance, creator=str(creator),
                                reservation_created_at=timestamp(now), purpose=self.identity.release_mode)
                    record = Record(self.identity.channel, self.identity.key, self.identity.source.upstream_sha,
                                    now, canonical(data).decode())
                    return self.journal.append(reserve(record, str(uuid4()), now, now+timedelta(hours=6)))
                if snapshot.record.upstream_sha != self.identity.source.upstream_sha:
                    raise ValueError('Journal source identity drift')
                snapshot = Reconciler(self.journal, self.evidence).refresh(snapshot, now)
                r = snapshot.record
                if (r.channel == 'stable' and r.state == BuildState.SUCCEEDED
                        and provenance(r).get('purpose') == 'dry-run' and self.identity.release_mode != 'dry-run'):
                    if self.evidence.run(r)['status'] != 'completed':
                        raise ValueError('Cannot upgrade an active dry-run')
                    return self.journal.append(reserve_upgrade(r, str(uuid4()), self.identity.release_mode,
                                               str(creator), now, now+timedelta(hours=6)), snapshot)
                if r.state == BuildState.FAILED and r.policy_state == PolicyState.COOLDOWN and r.next_retry_at and now >= r.next_retry_at:
                    # Reconciler has just verified the exact bound run is terminal.
                    return self.journal.append(reserve_retry(r, str(uuid4()), now, now+timedelta(hours=6), creator=str(creator), purpose=self.identity.release_mode), snapshot)
                return snapshot
            except Conflict:
                continue
        raise Conflict('Admission contention exceeds bounded reevaluation')

    def dispatch(self, snapshot, inputs, now):
        allowed = {'release_mode', 'include_wayland'}
        if self.identity.channel == 'stable':
            allowed.add('upstream_ref')
            if inputs.get('upstream_ref') != self.source_provenance.get('upstream_ref') or not re.fullmatch(r'v?[0-9]+\.[0-9]+\.[0-9]+', str(inputs.get('upstream_ref',''))):
                raise ValueError('Stable dispatch must use the resolved official tag')
        if (inputs.get('release_mode') != 'draft' or inputs.get('include_wayland') is not self.identity.wayland_included
                or set(inputs) != allowed):
            raise ValueError('Routing only authorizes the frozen private Draft configuration')
        if snapshot is None or snapshot.record.reservation_state != ReservationState.RESERVED:
            return False
        try:
            self.journal.append(dispatch_intent(snapshot.record, snapshot.record.reservation_id,
                                               snapshot.record.fence, str(uuid4()), now), snapshot)
        except Conflict:
            return False
        # Durable intent precedes HTTP. Any HTTP/transport error remains UNKNOWN;
        # a later router never replays it, but a verified late run can bind it.
        workflow = WORKFLOWS[self.identity.channel].split('/')[-1]
        self.api.request('POST', f'repos/{self.repo}/actions/workflows/{workflow}/dispatches',
                         {'ref': 'main', 'inputs': inputs})
        return True

    def admit(self, snapshot, run, now):
        if snapshot is None:
            return False
        r = snapshot.record
        if (run.get('repository', {}).get('full_name') != self.repo
                or run.get('head_repository', {}).get('full_name') != self.repo
                or run.get('head_branch') != 'main' or run.get('event') != 'workflow_dispatch'
                or run.get('path', '').split('@')[0] != WORKFLOWS[self.identity.channel]):
            raise ValueError('Foreign or untrusted admission run')
        if run.get('status') == 'completed':
            raise ValueError('Completed run cannot claim a new reservation')
        if type(run.get('run_attempt')) is not int or run['run_attempt'] != 1:
            raise ValueError('Native rerun is not a fresh coordinator dispatch')
        if r.channel == 'stable':
            old_purpose = provenance(r).get('purpose')
            compatible = old_purpose == self.identity.release_mode or (old_purpose in ('draft','release') and self.identity.release_mode in ('draft','release'))
            if not compatible:
                put_index(self.api, self.repo, str(run['id']), snapshot)
                return False
        if r.reservation_state in (ReservationState.RESERVED, ReservationState.DISPATCH_UNKNOWN):
            data = provenance(r)
            if str(run['id']) != data['creator'] and parse_time(run['created_at']) < parse_time(data['reservation_created_at']):
                raise ValueError('Run predates this reservation epoch')
            try:
                snapshot = self.journal.append(bind_verified(r, r.reservation_id, r.fence, str(run['id']),
                                                             run['head_sha'], run['run_attempt'], now,
                                                             official_run_id=self.source_provenance.get('official_run_id','')), snapshot)
                r = snapshot.record
            except Conflict:
                snapshot = self.journal.load()
                r = snapshot.record
        allowed = (r.workflow_run_id == str(run['id']) and r.state in (BuildState.QUEUED, BuildState.RUNNING)
                   and provenance(r).get('worker', {}).get('run_attempt') == run['run_attempt']
                   and r.policy_state.value == 'READY')
        put_index(self.api, self.repo, str(run['id']), snapshot)
        log_decision(r, 'ADMITTED' if allowed else 'SKIPPED')
        return allowed


def history(api, repo, channel):
    rows = []
    workflow = WORKFLOWS[channel].split('/')[-1]
    for page in range(1, 11):
        batch = api.request('GET', f'repos/{repo}/actions/workflows/{workflow}/runs?branch=main&event=workflow_dispatch&per_page=100&page={page}')['workflow_runs']
        rows.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('Incomplete workflow history')
    # Durable indexes distinguish managed attempts/denied admissions even after
    # their discovery artifact expires. Missing legacy evidence still blocks.
    return [r for r in rows if index_record(api, repo, r['id']) is None]


def nightly_history(api, repo, identity, current=''):
    from scripts.release import nightly
    rows = history(api, repo, 'nightly')
    if current:
        # The current run has not been indexed yet and must be present in history.
        rows = nightly.prior_history(rows, current)
    nightly.annotate_history(rows, identity.source.upstream_sha)
    state = nightly.route_state(rows, identity.historical_digest, identity.release_mode,
                                str(identity.wayland_included).lower(), current,
                                str(identity.android_signing_enabled).lower(), identity.source.upstream_sha)
    if state in ('ACTIVE', 'SUCCESS'):
        return state
    if state == 'UNKNOWN' or any(r.get('_nightly_identity') == identity.historical_digest for r in rows):
        return 'REVIEW'
    return 'EMPTY'


def recover_all(api, repo, channel, now):
    prefix = 'refs/heads/release-coordinator/v1/' + channel + '/'
    refs = api.request('GET', f'repos/{repo}/git/matching-refs/heads/release-coordinator/v1/{channel}/')
    if not isinstance(refs, list) or len(refs) > 1000:
        raise ValueError('Journal inventory requires operator maintenance')
    for row in refs:
        if not row['ref'].startswith(prefix):
            raise ValueError('Unexpected journal inventory')
        key = row['ref'][len(prefix):]
        journal = GitRefStore(api, repo, channel, key)
        snapshot = journal.load()
        if snapshot is None:
            raise ValueError('Journal disappeared during reconciliation')
        if snapshot.record.state != BuildState.SUCCEEDED:
            try:
                Reconciler(journal, ActionsEvidence(api, repo)).refresh(snapshot, now)
            except Conflict:
                pass  # Another fenced writer advanced it; no side effect follows.
            except (APIError, AmbiguousWrite, ValueError):
                # This verified key remains blocked. A different current key
                # must not be held hostage by an obsolete run's expired evidence.
                log_decision(snapshot.record, 'HISTORICAL_REVIEW_REQUIRED')


def route_nightly(data):
    repo = context('upstream-nightly.yml', ('schedule', 'workflow_dispatch'))
    from scripts.release import nightly
    data = dict(data, wayland_policy_sha256=nightly.wayland_policy_hash(True))
    identity = build(data, 'nightly', 'draft')
    api, now = GitHubAPI(), clock()
    recover_all(api, repo, 'nightly', now)
    coordinator = Coordinator(api, repo, identity, source_provenance=data)
    snapshot = coordinator.claim(now, os.environ['GITHUB_RUN_ID'], lambda: nightly_history(api, repo, identity))
    sent = coordinator.dispatch(snapshot, {'release_mode':'draft', 'include_wayland':True}, now)
    outputs(dispatched=sent, build_identity=identity.key)


def admit_nightly(path, digest):
    repo = context('nightly.yml', ('workflow_dispatch',))
    raw = path.read_bytes()
    hex_value(digest, 64)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Nightly discovery digest mismatch')
    discovery = json.loads(raw)
    identity = build(discovery, 'nightly', os.environ['RELEASE_MODE'])
    api, now = GitHubAPI(), clock()
    run_id = os.environ['GITHUB_RUN_ID']
    run = api.request('GET', f'repos/{repo}/actions/runs/{run_id}')
    if (str(run.get('id')) != run_id or run.get('head_sha') != os.environ['GITHUB_SHA']
            or run.get('head_repository', {}).get('full_name') != repo or run.get('head_branch') != 'main'
            or run.get('event') != 'workflow_dispatch' or run.get('path', '').split('@')[0] != WORKFLOWS['nightly']
            or run.get('status') == 'completed'
            or type(run.get('run_attempt')) is not int or run['run_attempt'] != 1):
        raise ValueError('Untrusted admission run')
    coordinator = Coordinator(api, repo, identity, source_provenance=discovery)
    snapshot = coordinator.claim(now, run_id, lambda: nightly_history(api, repo, identity, run_id))
    outputs(allow=coordinator.admit(snapshot, run, now), build_identity=identity.key)


def guard():
    channel = 'stable' if os.environ.get('GITHUB_WORKFLOW_REF') == repository()+'/.github/workflows/tag.yml@refs/heads/main' else 'nightly'
    repo = context('tag.yml' if channel == 'stable' else 'nightly.yml', ('workflow_dispatch',))
    api = GitHubAPI()
    indexed = index_record(api, repo, os.environ['GITHUB_RUN_ID'])
    if indexed is None:
        raise ValueError('No durable admission receipt')
    journal = GitRefStore(api, repo, indexed.channel, indexed.build_identity)
    snapshot = journal.load()
    r = snapshot.record if snapshot else None
    if (r is None or r.channel != channel or r.workflow_run_id != os.environ['GITHUB_RUN_ID']
            or (r.reservation_id, r.fence) != (indexed.reservation_id, indexed.fence)
            or r.state not in (BuildState.QUEUED, BuildState.RUNNING) or r.policy_state.value != 'READY'
            or (os.environ.get('UPSTREAM_EXPECTED_SHA') and r.upstream_sha != os.environ['UPSTREAM_EXPECTED_SHA'])
            or provenance(r).get('worker', {}).get('custom_repository_sha') != os.environ['GITHUB_SHA']
            or str(provenance(r).get('worker', {}).get('run_attempt')) != os.environ['GITHUB_RUN_ATTEMPT']):
        raise ValueError('Stale or invalid worker admission')
    # Worker identity comes from this running GitHub job's immutable context.
    # Only state writers query Actions; ordinary workers keep Contents read.
    log_decision(r, 'WORKER_GUARD_PASSED')


def observe():
    repo = context('release-coordinator.yml', ('workflow_run',))
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['workflow_run']
    api = GitHubAPI()
    indexed = index_record(api, repo, event['id'])
    if indexed is None or indexed.workflow_run_id != str(event['id']):
        return
    snapshot = GitRefStore(api, repo, indexed.channel, indexed.build_identity).load()
    r = snapshot.record
    if (r.reservation_id, r.fence, r.workflow_run_id) != (indexed.reservation_id, indexed.fence, str(event['id'])):
        return  # Stale completion cannot modify a new reservation.
    worker = provenance(r).get('worker', {})
    if event.get('head_sha') != worker.get('custom_repository_sha') or event.get('run_attempt') != worker.get('run_attempt'):
        return
    Reconciler(GitRefStore(api, repo, r.channel, r.build_identity), ActionsEvidence(api, repo)).refresh(snapshot, clock())



def stable_history(api, repo, identity, current=''):
    from scripts.release import stable_router
    rows=history(api,repo,'stable')
    selected=[]
    suffix=f" / wayland={str(identity.wayland_included).lower()} / android-signing={str(identity.android_signing_enabled).lower()}"
    for row in rows:
        if str(row['id'])==current: continue
        title=row.get('display_title','')
        if not title.startswith('Stable ') or suffix not in title: continue
        if row.get('status')!='completed': return 'ACTIVE'
        # Reconstruct every relevant lock, including old manually named runs.
        if stable_router.recorded_identity(row)!=identity.historical_digest: continue
        if row.get('conclusion')=='success' and ' / dry-run /' not in title: return 'SUCCESS'
        if ' / dry-run /' in title and row.get('conclusion')=='success': continue
        selected.append(row)
    return 'REVIEW' if selected else 'EMPTY'


def route_stable():
    from scripts.release import stable_router, stable_lock
    repo=context('upstream-stable.yml',('schedule','workflow_dispatch'))
    stable_router.verify_context()
    data=stable_router.discovery()
    api,now=GitHubAPI(),clock()
    recover_all(api,repo,'stable',now)
    completed=stable_router.latest_completed_version()
    same=(os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and os.environ.get('ALLOW_SAME_VERSION','false').lower()=='true')
    if completed and stable_router.version_tuple(data['version'])<=stable_router.version_tuple(completed) and not same:
        outputs(dispatched=False,state='VERSION_NOT_ADVANCED');return
    if stable_router.existing_build(data):
        outputs(dispatched=False,state='COMPLETE_RELEASE_EXISTS');return
    locked=stable_lock.plan(data,data['patchset'])
    identity=build(locked,'stable','draft')
    coordinator=Coordinator(api,repo,identity,source_provenance=locked)
    snapshot=coordinator.claim(now,os.environ['GITHUB_RUN_ID'],lambda:stable_history(api,repo,identity))
    sent=coordinator.dispatch(snapshot,dict(release_mode='draft',include_wayland=True,upstream_ref=data['upstream_tag']),now)
    outputs(dispatched=sent,build_identity=identity.key)


def admit_stable():
    from scripts.release import stable_lock
    repo=context('tag.yml',('workflow_dispatch',))
    locked=stable_lock.current() # Existing digest, source/run/custom/options gates.
    identity=build(locked,'stable',os.environ['RELEASE_MODE'])
    api,now=GitHubAPI(),clock()
    run_id=os.environ['GITHUB_RUN_ID']
    run=api.request('GET',f'repos/{repo}/actions/runs/{run_id}')
    if (str(run.get('id'))!=run_id or run.get('head_sha')!=os.environ['GITHUB_SHA']
            or run.get('repository',{}).get('full_name')!=repo
            or run.get('head_repository',{}).get('full_name')!=repo or run.get('head_branch')!='main'
            or run.get('event')!='workflow_dispatch' or run.get('path','').split('@')[0]!=WORKFLOWS['stable']
            or run.get('status')=='completed' or type(run.get('run_attempt')) is not int or run['run_attempt']!=1):
        raise ValueError('Untrusted Stable admission run')
    coordinator=Coordinator(api,repo,identity,source_provenance=locked)
    snapshot=coordinator.claim(now,run_id,lambda:stable_history(api,repo,identity,run_id))
    outputs(allow=coordinator.admit(snapshot,run,now),build_identity=identity.key)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('admit-nightly', 'admit-stable', 'guard', 'observe', 'grant'))
    parser.add_argument('--discovery', type=Path)
    parser.add_argument('--digest')
    args = parser.parse_args()
    if args.mode == 'admit-nightly':
        admit_nightly(args.discovery, args.digest)
    elif args.mode == 'admit-stable':
        admit_stable()
    elif args.mode == 'guard':
        guard()
    elif args.mode == 'observe':
        observe()
    else:
        repo = context('release-coordinator.yml', ('workflow_dispatch',))
        channel, key = os.environ['RETRY_CHANNEL'], os.environ['RETRY_IDENTITY']
        api, now = GitHubAPI(), clock()
        journal = GitRefStore(api, repo, channel, key)
        snapshot = journal.load()
        if snapshot is None:
            raise ValueError('Cannot grant an unknown historical identity')
        evidence = ActionsEvidence(api, repo)
        if evidence.run(snapshot.record)['status'] != 'completed':
            raise ValueError('Cannot retry an active run')
        snapshot = Reconciler(journal, evidence).refresh(snapshot, now)
        method = grant_upgrade if snapshot.record.state == BuildState.SUCCEEDED else grant_retry
        journal.append(method(snapshot.record, os.environ['GITHUB_ACTOR'], os.environ['RETRY_REASON'], now), snapshot)


if __name__ == '__main__':
    main()
