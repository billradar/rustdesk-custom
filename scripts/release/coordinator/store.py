"""Git-ref journal: immutable single-parent snapshots and non-force updates.

No state branch is checked out or executed. No release/tag/main ref is writable
through this interface. A conflicting/ambiguous mutation is never retried here.
"""
from base64 import b64decode
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import json
import os
import re
import time
import urllib.error
import urllib.request

from .identity import canonical, hex_value
from .model import (BuildState, Event, PolicyState, Record, ReservationState,
                    advance, bind, dispatch_unknown, reserve, utc)


class Conflict(RuntimeError):
    """Another writer owns the journal head; reload and re-evaluate."""


class AmbiguousWrite(RuntimeError):
    """The write outcome is unknown; do not replay a side effect."""


class APIError(RuntimeError):
    def __init__(self, status, retry_after=0):
        super().__init__(f'GitHub API status {status}')
        self.status = status
        self.retry_after = retry_after


class GitHubAPI:
    def __init__(self, token=None, *, sleep=time.sleep):
        self.token = token if token is not None else os.environ.get('GH_TOKEN', '')
        if not self.token:
            raise ValueError('GitHub API token required')
        self.sleep = sleep

    def request(self, method, path, data=None):
        if not re.fullmatch(r'repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_./?=&%-]+', path):
            raise ValueError('Unsafe API path')
        raw = canonical(data) if data is not None else None
        request = urllib.request.Request('https://api.github.com/' + path, data=raw, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read(1024 * 1024 + 1)
                    if len(body) > 1024 * 1024:
                        raise ValueError('Oversized API response')
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as error:
                # Do not log the HTTP body or Authorization headers.
                delay = error.headers.get('Retry-After', '0')
                delay = int(delay) if delay.isdigit() else 0
                if method == 'GET' and attempt < 2 and delay <= 30 and (error.code == 429 or 500 <= error.code < 600):
                    self.sleep(max(delay, 2 ** attempt))
                    continue
                raise APIError(error.code, delay) from None
            except (TimeoutError, urllib.error.URLError):
                if method == 'GET' and attempt < 2:
                    self.sleep(2 ** attempt)
                    continue
                raise AmbiguousWrite('API transport outcome unknown') from None


TIMES = ('created_at', 'started_at', 'completed_at', 'lease_expires_at', 'next_retry_at')


def timestamp(value):
    return utc(value).isoformat().replace('+00:00', 'Z')


def parse_time(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('UTC timestamp required')
    return utc(datetime.fromisoformat(value[:-1] + '+00:00'))


def encode_record(record):
    data = asdict(record)
    for key in ('state', 'reservation_state', 'policy_state'):
        data[key] = data[key].value
    for key in TIMES:
        data[key] = timestamp(data[key]) if data[key] is not None else None
    return data


def decode_record(data):
    if type(data) is not dict or set(data) != {f.name for f in fields(Record)}:
        raise ValueError('Unknown or incomplete record schema')
    data = dict(data)
    for key in TIMES:
        data[key] = parse_time(data[key]) if data[key] is not None else None
    for key, enum in (('state', BuildState), ('reservation_state', ReservationState), ('policy_state', PolicyState)):
        data[key] = enum(data[key])
    return Record(**data)


def validate_event(event):
    """Reconstruct the supported transition; arbitrary forged Events are rejected."""
    before, after, at = event.before, event.after, event.at
    args = (before, before.reservation_id, before.fence)
    if event.action == 'reserve':
        expected = reserve(before, after.reservation_id, at, after.lease_expires_at)
    elif event.action == 'dispatch_unknown':
        expected = dispatch_unknown(*args, at)
    elif event.action == 'bind':
        expected = bind(*args, after.workflow_run_id, at)
    elif event.action == 'advance':
        expected = advance(*args, after.state, at, failure_class=after.failure_class,
                           failure_stage=after.failure_stage, failure_reason=after.failure_reason)
    else:
        from .transitions import validate_additional
        validate_additional(event)
        return
    if expected != event:
        raise ValueError('Event differs from validated state transition')


@dataclass(frozen=True)
class Snapshot:
    sha: str
    record: Record
    at: datetime


class GitRefStore:
    """One append-only ref per (repository, channel, build identity).

    Atomicity relies on single-parent commits, force=false and never deleting,
    merging or resetting ledger refs. GitHub REST has no expected-old-SHA field.
    """
    def __init__(self, api, repository, channel, identity, *, namespace='release-coordinator/v1'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Invalid repository')
        if channel not in ('stable', 'nightly'):
            raise ValueError('Invalid channel')
        hex_value(identity, 64)
        if namespace not in ('release-coordinator/v1', 'coordinator-integration/v1'):
            raise ValueError('Unsafe state namespace')
        self.api = api
        self.base = 'repos/' + repository + '/git/'
        self.channel, self.identity = channel, identity
        self.ref = 'heads/' + namespace + '/' + channel + '/' + identity

    def _check(self, record):
        if record.channel != self.channel or record.build_identity != self.identity:
            raise ValueError('State journal identity mismatch')

    def _blob(self, sha):
        hex_value(sha, 40)
        row = self.api.request('GET', self.base + 'blobs/' + sha)
        if row.get('encoding') != 'base64':
            raise ValueError('Unsupported state blob encoding')
        raw = b64decode(''.join(row['content'].split()), validate=True)
        if len(raw) > 65536:
            raise ValueError('Oversized state journal')
        data = json.loads(raw)
        if canonical(data) != raw:
            raise ValueError('Noncanonical state journal')
        return data

    def load(self):
        try:
            ref = self.api.request('GET', self.base + 'ref/' + self.ref)
        except APIError as error:
            if error.status == 404:
                return None
            raise
        if ref.get('ref') != 'refs/' + self.ref or ref['object']['type'] != 'commit':
            raise ValueError('Invalid state ref')
        sha = ref['object']['sha']
        hex_value(sha, 40)
        commit = self.api.request('GET', self.base + 'commits/' + sha)
        parents = [p['sha'] for p in commit['parents']]
        if len(parents) > 1:
            raise ValueError('State journal cannot contain merges')
        tree = self.api.request('GET', self.base + 'trees/' + commit['tree']['sha'])
        entries = {e['path']: e for e in tree['tree']}
        if (tree.get('truncated') or len(tree['tree']) != 2 or set(entries) != {'state.json', 'event.json'}
                or any(e['type'] != 'blob' or e['mode'] != '100644' for e in entries.values())):
            raise ValueError('Invalid state-only tree')
        state = self._blob(entries['state.json']['sha'])
        audit = self._blob(entries['event.json']['sha'])
        if (set(audit) != {'schema_version', 'previous_sha', 'at', 'action', 'before', 'after'}
                or type(audit['schema_version']) is not int or audit['schema_version'] != 1
                or audit['previous_sha'] != (parents[0] if parents else '')):
            raise ValueError('Invalid journal ancestry/schema')
        event = Event(parse_time(audit['at']), audit['action'], decode_record(audit['before']), decode_record(audit['after']))
        validate_event(event)
        record = decode_record(state)
        self._check(record)
        if record != event.after:
            raise ValueError('State and audit event disagree')
        if parents:
            parent = self.api.request('GET', self.base + 'commits/' + parents[0])
            parent_tree = self.api.request('GET', self.base + 'trees/' + parent['tree']['sha'])
            matches = [e for e in parent_tree['tree'] if e['path'] == 'state.json'
                       and e['mode'] == '100644' and e['type'] == 'blob']
            if parent_tree.get('truncated') or len(matches) != 1:
                raise ValueError('Missing parent state')
            if decode_record(self._blob(matches[0]['sha'])) != event.before:
                raise ValueError('Event does not follow its parent state')
        if not parents and (event.action != 'reserve' or event.before.fence != 0):
            raise ValueError('Invalid initial state transition')
        return Snapshot(sha, record, event.at)

    def append(self, event, previous=None):
        validate_event(event)
        self._check(event.before)
        self._check(event.after)
        if previous is None:
            if event.action != 'reserve' or event.before.fence != 0:
                raise ValueError('Initial journal must reserve a fresh discovery')
        elif event.before != previous.record or event.at < previous.at:
            raise ValueError('Stale snapshot or out-of-order event')
        if previous is not None:
            hex_value(previous.sha, 40)
        parent = previous.sha if previous else ''
        audit = dict(schema_version=1, previous_sha=parent, at=timestamp(event.at),
                     action=event.action, before=encode_record(event.before), after=encode_record(event.after))
        entries = []
        for name, value in (('state.json', encode_record(event.after)), ('event.json', audit)):
            raw = canonical(value)
            if len(raw) > 65536:
                raise ValueError('Oversized state event')
            blob = self.api.request('POST', self.base + 'blobs', {'content': raw.decode(), 'encoding': 'utf-8'})
            entries.append(dict(path=name, mode='100644', type='blob', sha=blob['sha']))
        tree = self.api.request('POST', self.base + 'trees', {'tree': entries})
        person = dict(name='Release Coordinator', email='release-coordinator@users.noreply.github.com', date=timestamp(event.at))
        commit = self.api.request('POST', self.base + 'commits',
            dict(message='coordinator: ' + event.action, tree=tree['sha'], parents=[parent] if parent else [],
                 author=person, committer=person))
        candidate = commit['sha']
        hex_value(candidate, 40)
        try:
            if previous:
                response = self.api.request('PATCH', self.base + 'refs/' + self.ref, {'sha': candidate, 'force': False})
            else:
                response = self.api.request('POST', self.base + 'refs', {'ref': 'refs/' + self.ref, 'sha': candidate})
            if (not isinstance(response, dict) or response.get('ref') != 'refs/' + self.ref
                    or response.get('object', {}).get('sha') != candidate):
                raise AmbiguousWrite('Unexpected ref response')
        except (APIError, AmbiguousWrite) as error:
            # One read-back; no replay. If another event already followed ours,
            # reconciliation must establish ancestry/ownership separately.
            actual = self.load()
            if actual is not None and actual.sha == candidate:
                return actual
            if isinstance(error, APIError) and error.status in (409, 422) and actual is not None:
                raise Conflict('State ref changed; re-evaluate admission') from None
            raise AmbiguousWrite('Ref update outcome requires reconciliation') from None
        return Snapshot(candidate, event.after, event.at)
