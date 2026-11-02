"""Opt-in GitHub Git API smoke tests, confined to synthetic state-only test refs.

No Actions dispatch, signing, Release, tag, production journal or ref deletion API.
Live tests retain their three refs as audit evidence. Never execute these commits.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Barrier, Lock
from uuid import uuid4

from .identity import canonical
from .model import Record, bind, reserve
from .store import APIError, AmbiguousWrite, Conflict, GitHubAPI, GitRefStore
from .transitions import finish, grant_retry, reserve_retry
from .retry import Failure

NAMESPACE = 'coordinator-integration/v1'
BRANCH = 'coordinator/06-isolated-api-validation-20261102'
WORKFLOW = '.github/workflows/release-coordinator-integration.yml'
REPOSITORY = 'billradar/rustdesk-custom'


def trusted_context():
    repo = os.environ.get('GITHUB_REPOSITORY')
    if repo != REPOSITORY or os.environ.get('COORDINATOR_INTEGRATION_ALLOW_WRITE') != 'true':
        raise ValueError('Explicit isolated test context required')
    event = os.environ.get('GITHUB_EVENT_NAME')
    workflow = os.environ.get('GITHUB_WORKFLOW_REF')
    if event == 'pull_request':
        data = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        pr = data['pull_request']
        number = data['number']
        if (type(number) is not int or number <= 0 or pr['head']['repo']['full_name'] != repo
                or pr['base']['repo']['full_name'] != repo or pr['head']['ref'] != BRANCH
                or os.environ.get('GITHUB_HEAD_REF') != BRANCH
                or workflow != f'{repo}/{WORKFLOW}@refs/pull/{number}/merge'
                or os.environ.get('GITHUB_REF') != f'refs/pull/{number}/merge'):
            raise ValueError('Untrusted test pull request')
    elif event == 'workflow_dispatch':
        if workflow != f'{repo}/{WORKFLOW}@refs/heads/main' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
            raise ValueError('Manual tests require reviewed main workflow')
    else:
        raise ValueError('Unsupported integration event')
    if not re.fullmatch('[1-9][0-9]*', os.environ.get('GITHUB_RUN_ID', '')):
        raise ValueError('Test run ID required')
    return repo


class IsolatedAPI:
    """Allowlist transport for the real, unmodified GitRefStore implementation."""
    def __init__(self, api, repository):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Invalid test repository')
        self.api, self.base = api, 'repos/'+repository+'/git/'
        self.refs, self.commits = set(), set()
        self.lock = Lock()
        self.barrier = None
        self.barrier_refs = set()
        self.fault = ''
        self.calls = 0

    def register(self, ref):
        if not re.fullmatch('heads/'+NAMESPACE+r'/(stable|nightly)/[0-9a-f]{64}', ref):
            raise ValueError('Not an isolated test ref')
        self.refs.add(ref)
        try:
            self.request('GET', self.base+'ref/'+ref)
        except APIError as error:
            if error.status == 404:
                return
            raise
        raise ValueError('Test ref already exists; never adopt existing resources')

    def request(self, method, path, data=None):
        if not path.startswith(self.base):
            raise ValueError('Integration API is Git-only in the test repository')
        suffix = path[len(self.base):]
        ref = ''
        allowed = False
        if method == 'GET':
            allowed = (suffix.startswith('ref/') and suffix[4:] in self.refs) or bool(
                re.fullmatch(r'(blobs|trees|commits)/[0-9a-f]{40}', suffix))
        elif method == 'POST' and suffix == 'blobs':
            allowed = (isinstance(data, dict) and set(data) == {'content','encoding'}
                       and data['encoding'] == 'utf-8' and isinstance(data['content'], str)
                       and len(data['content'].encode()) <= 65536)
            if allowed:
                raw = data['content'].encode()
                allowed = canonical(json.loads(raw)) == raw
        elif method == 'POST' and suffix == 'trees':
            rows = data.get('tree', []) if isinstance(data, dict) else []
            allowed = (set(data) == {'tree'} and len(rows) == 2
                and {r.get('path') for r in rows} == {'state.json','event.json'}
                and all(set(r) == {'path','mode','type','sha'} and r['mode'] == '100644'
                        and r['type'] == 'blob' and re.fullmatch('[0-9a-f]{40}', r['sha']) for r in rows))
        elif method == 'POST' and suffix == 'commits':
            allowed = (isinstance(data, dict) and set(data) == {'message','tree','parents','author','committer'}
                and isinstance(data['parents'], list) and len(data['parents']) <= 1
                and all(p in self.commits for p in data['parents'])
                and re.fullmatch('[0-9a-f]{40}', data['tree']) is not None
                and data['message'].startswith('coordinator: '))
        elif method == 'POST' and suffix == 'refs':
            ref = data.get('ref','').removeprefix('refs/') if isinstance(data, dict) else ''
            allowed = set(data) == {'ref','sha'} and ref in self.refs and data['sha'] in self.commits
        elif method == 'PATCH' and suffix.startswith('refs/'):
            ref = suffix[5:]
            allowed = (isinstance(data, dict) and set(data) == {'sha','force'} and data['force'] is False
                       and ref in self.refs and data['sha'] in self.commits)
        if not allowed:
            raise ValueError('Rejected operation outside isolated state-only test API')
        with self.lock:
            self.calls += 1
            fault = self.fault if ref else ''
            if fault:
                self.fault = ''
        if self.barrier is not None and ref in self.barrier_refs:
            self.barrier.wait(timeout=60)
        if fault == 'before_503':
            raise APIError(503)
        result = self.api.request(method, path, data)
        if method == 'POST' and suffix == 'commits':
            with self.lock:
                self.commits.add(result['sha'])
        if fault == 'after_timeout':
            raise AmbiguousWrite('Injected lost ref-update acknowledgement')
        return result


def require(value, message):
    if not value:
        raise AssertionError(message)


def exercise(api, repository, session):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    def fresh(channel, label):
        key = hashlib.sha256(f'{repository}:{session}:{channel}:{label}'.encode()).hexdigest()
        record = Record(channel, key, 'a'*40, now, canonical({'fixture':'synthetic','session':session}).decode())
        journal = GitRefStore(api, repository, channel, key, namespace=NAMESPACE)
        api.register(journal.ref)
        return journal, reserve(record, str(uuid4()), now, now+timedelta(seconds=1))
    def race(journals, events, previous):
        api.barrier, api.barrier_refs = Barrier(2), {j.ref for j in journals}
        def append(i):
            try:
                return journals[i].append(events[i], previous[i])
            except Conflict:
                return None
        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                return list(workers.map(append, (0,1)))
        finally:
            api.barrier, api.barrier_refs = None, set()

    journal, event = fresh('stable','race')
    other = reserve(event.before,str(uuid4()),now,now+timedelta(seconds=1))
    results = race([journal,journal],[event,other],[None,None])
    require(sum(s is not None for s in results)==1, 'Same-identity create must have one winner')
    snapshot = journal.load()
    require(snapshot in results,'Reload must match the winning root')
    checks = ['same_identity_one_reservation']

    first, a = fresh('stable','independent');second, b = fresh('nightly','independent')
    independent = race([first,second],[a,b],[None,None])
    require(all(independent),'Different identities/channels must reserve independently')
    checks.append('different_identity_and_channel_independence')

    events = [bind(snapshot.record,snapshot.record.reservation_id,snapshot.record.fence,str(i),now) for i in (101,102)]
    results = race([journal,journal],events,[snapshot,snapshot])
    require(sum(s is not None for s in results)==1,'Competing siblings must have one FF winner')
    bound = journal.load()
    require(bound in results,'Restart must recover the winner')
    require(GitRefStore(api,repository,'stable',bound.record.build_identity,namespace=NAMESPACE).load()==bound,
            'A fresh worker must recover persistent state')
    checks.extend(['sibling_update_one_winner','worker_restart_recovery'])

    api.fault = 'after_timeout'
    old = independent[1]
    lost = second.append(bind(old.record,old.record.reservation_id,old.record.fence,'103',now),old)
    require(second.load()==lost,'Lost acknowledgement must be recovered by readback')
    checks.append('accepted_write_lost_acknowledgement')

    api.fault = 'before_503'
    failed_event = bind(independent[0].record,independent[0].record.reservation_id,independent[0].record.fence,'104',now)
    try:
        first.append(failed_event,independent[0])
    except AmbiguousWrite:
        pass
    else:
        raise AssertionError('503 must not become a successful reservation update')
    require(first.load()==independent[0],'Failed write must not advance the authoritative head')
    checks.append('write_503_no_replay')

    # Synthetic terminal evidence tests storage fencing only, never actual Actions completion.
    r=bound.record
    ended=journal.append(finish(r,r.reservation_id,r.fence,None,now+timedelta(seconds=2),False,
                               Failure.SDK.value,'fixture','synthetic prebuild termination'),bound)
    granted=journal.append(grant_retry(ended.record,'integration','Synthetic reviewed retry',now+timedelta(seconds=3)),ended)
    replacement=journal.append(reserve_retry(granted.record,str(uuid4()),now+timedelta(seconds=4),
                               now+timedelta(hours=1)),granted)
    try:
        journal.append(finish(r,r.reservation_id,r.fence,None,now+timedelta(seconds=5),False,
                              Failure.UNKNOWN.value,'fixture','stale synthetic worker'),bound)
    except Conflict:
        pass
    else:
        raise AssertionError('Old worker result must not overwrite a newer epoch')
    require(journal.load()==replacement and replacement.record.attempt==0,'Fencing and prebuild attempt accounting failed')
    checks.append('expired_epoch_stale_worker_rejected')
    return dict(schema_version=1,session=session,result='PASS',checks=checks,
                refs=sorted('refs/'+r for r in api.refs),api_calls=api.calls,
                limitation='Git storage integration only; synthetic run evidence, no Actions dispatch or signing/publication')


def main():
    repository=trusted_context()
    api=IsolatedAPI(GitHubAPI(),repository)
    session=os.environ['GITHUB_RUN_ID']+'-'+str(uuid4())
    result=dict(schema_version=1,session=session,result='FAIL',attempted_refs=[])
    try:
        result=exercise(api,repository,session)
    except Exception as error:
        result['failure_type']=type(error).__name__
        raise
    finally:
        result['attempted_refs']=sorted('refs/'+r for r in api.refs)
        result['api_calls']=api.calls
        path=Path('.work/coordinator-integration/summary.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        print(json.dumps(result,sort_keys=True))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:
                stream.write('## Isolated coordinator Git API verification\n\n```json\n'+json.dumps(result,indent=2)+'\n```\n')


if __name__=='__main__':
    main()
