"""Reviewed, content-addressed legacy evidence. Decisions can only block work.

Imports are offline Git changes reviewed through a PR, never state-worker writes.
No reservation, retry grant, signing or publication capability exists here.
"""
from dataclasses import asdict
import copy
import hashlib
import json
from pathlib import Path
import re

from .identity import BuildIdentity, SourceIdentity, canonical, digest, hex_value

ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = 'billradar/rustdesk-custom'
AUDIT = ROOT/'docs/audits/coordinator-preactivation-20261102/migration-plan.json'
AUDIT_SHA256 = '9cb18b82b52c6f4aa12c80dc6fe9b3053c090099708048787b94c65d59209b65'
CATALOG = ROOT/'metadata/release/coordinator-legacy'
WORKFLOWS = {'stable': '.github/workflows/tag.yml', 'nightly': '.github/workflows/nightly.yml'}
RUN_FIELDS = ('id', 'run_attempt', 'head_sha', 'head_branch', 'event', 'path',
              'status', 'conclusion', 'display_title')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audited_rows():
    raw = AUDIT.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == AUDIT_SHA256, 'Reviewed source audit changed')
    value = json.loads(raw)
    require(value['repository'] == REPOSITORY and value['migration_plan_only'] is True,
            'Unexpected source audit')
    return {row['run_id']: row for row in value['runs']}


def document(row):
    """Archive content is verified byte-for-byte; no current patch/policy fill-in."""
    candidates = []
    for artifact in row['artifact_evidence']:
        raw = artifact['archived_document_utf8'].encode('utf-8')
        require(len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == artifact['json_sha256'],
                'Archived JSON digest mismatch')
        hex_value(artifact['download_sha256'], 64)
        require(artifact['archive_digest_verified'] is True
                and artifact['digest'] == 'sha256:'+artifact['download_sha256'], 'Unverified archive digest')
        value = json.loads(raw)
        require(type(value) is dict, 'Invalid archived identity document')
        if row['channel'] == 'nightly':
            if artifact['name'] == f"nightly-discovery-{row['run_id']}":
                candidates.append(value)
        elif artifact['name'] == f"stable-build-lock-{row['run_id']}-{row['latest_attempt']}":
            candidates.append(value)
    require(len(candidates) <= 1, 'Conflicting archived primary documents')
    return candidates[0] if candidates else None


def source_hint(row):
    values = {json.loads(a['archived_document_utf8']).get('upstream_sha') for a in row['artifact_evidence']}
    values.discard(None);values.discard('')
    require(len(values) <= 1, 'Conflicting archived source SHA')
    if not values:
        return ''
    result = values.pop();hex_value(result, 40)
    return result


def identity(row):
    if row['disposition'] != 'VERIFIED_LEGACY_SUCCESS_IDENTITY':
        return None
    from scripts.upstream.patchsets import patchset_for_version
    require(row['latest_status'] == 'completed' and row['latest_conclusion'] == 'success'
            and row['no_build_reuse'] is False and row['latest_attempt'] in row['observed_compile_attempts'],
            'A no-build/unknown result is not legacy producer success')
    options = row['options']
    result = BuildIdentity(row['channel'], SourceIdentity(**row['source_identity']),
        options['wayland_included'], options['wayland_policy_sha256'],
        options['android_signing_enabled'], options['release_mode'])
    require(options['release_mode'] in ('draft', 'release'), 'Dry-run migration requires separate purpose review')
    require(result.key == row['coordinator_build_identity']
            and result.historical_digest == row['legacy_build_identity'], 'Legacy identity mapping conflict')
    data = document(row)
    require(data is not None, 'Producer identity document missing')
    for key, value in asdict(result.source).items():
        if key != 'upstream_repository':
            require(data.get(key) == value, 'Archived source identity mismatch')
    version = data.get('version') if result.channel == 'stable' else data.get('upstream_version')
    require(result.source.patchset == patchset_for_version(version), 'Archived patchset/version mismatch')
    require(data.get('wayland_policy_sha256', '') == result.wayland_policy_sha256, 'Archived Wayland mismatch')
    if result.channel == 'stable':
        require(data.get('schema') == 'stable-build-lock-v1' and data.get('channel') == 'stable'
                and data.get('custom_repository_sha') == row['custom_repository_sha']
                and data.get('workflow_run') == str(row['run_id'])
                and data.get('build_identity') == result.historical_digest
                and data.get('wayland_included') is result.wayland_included
                and data.get('android_signing_enabled') is result.android_signing_enabled,
                'Archived Stable provenance/options mismatch')
    else:
        require(data.get('channel') == 'nightly' and data.get('upstream_repository') == 'rustdesk/rustdesk',
                'Archived Nightly provenance mismatch')
        suffix = f" / {result.release_mode} / wayland={str(result.wayland_included).lower()} / android-signing={str(result.android_signing_enabled).lower()}"
        require(row['title'].endswith(suffix), 'Archived Nightly options mismatch')
        official = row['verified_official_source_evidence']
        require(official['repository'] == official['head_repository'] == 'rustdesk/rustdesk'
                and official['head_sha'] == result.source.upstream_sha
                and official['path'] == '.github/workflows/flutter-nightly.yml'
                and official['head_branch'] == 'master' and official['status'] == 'completed'
                and official['conclusion'] == 'success', 'Unverified archived official source')
        # A disappeared original official run ID remains provenance. A separately
        # verified successful same-SHA official run does not rewrite that ID.
    return result


def fingerprint(run):
    return {key: run.get(key) for key in RUN_FIELDS} | {
        'repository': run.get('repository', {}).get('full_name'),
        'head_repository': run.get('head_repository', {}).get('full_name')}


def validate_observation(row, observation):
    require(set(observation) == {'run','attempts'}, 'Unknown observation schema')
    event = observation['run'].get('event')
    require(event in ('workflow_dispatch', 'schedule'), 'Untrusted historical event')
    if row['disposition'] == 'VERIFIED_LEGACY_SUCCESS_IDENTITY':
        require(event == 'workflow_dispatch', 'Scheduled legacy producer needs separate review')
    expected = dict(id=row['run_id'], run_attempt=row['latest_attempt'], head_sha=row['custom_repository_sha'],
        head_branch='main', event=event, path=WORKFLOWS[row['channel']],
        status=row['latest_status'], conclusion=row['latest_conclusion'], display_title=row['title'],
        repository=REPOSITORY, head_repository=REPOSITORY)
    require(observation['run'] == expected, 'Historical run changed or belongs to another producer')
    require(type(row['run_id']) is int and row['run_id'] > 0 and type(row['latest_attempt']) is int
            and row['latest_attempt'] > 0, 'Invalid historical run/attempt')
    hex_value(row['custom_repository_sha'], 40)
    attempts = observation['attempts']
    require([a['attempt'] for a in attempts] == list(range(1, row['latest_attempt']+1)), 'Incomplete attempt inventory')
    compiled = []
    from .store import parse_time
    for attempt in attempts:
        require(set(attempt) == {'attempt','job_count','jobs_sha256','compile_steps'}, 'Unknown attempt schema')
        require(type(attempt['attempt']) is int and attempt['attempt'] > 0, 'Invalid observed attempt')
        hex_value(attempt['jobs_sha256'], 64)
        require(type(attempt['job_count']) is int and attempt['job_count'] > 0, 'Missing historical jobs')
        if attempt['compile_steps']:
            compiled.append(attempt['attempt'])
        for step in attempt['compile_steps']:
            require(type(step['job_id']) is int and step['job_id'] > 0
                    and step['name'] in ('Official-compatible compile, package and independent gates', 'Build and verify selected variant')
                    and step['status'] == 'completed' and step['conclusion'] in ('success','failure','cancelled','timed_out'),
                    'Invalid observed compile evidence')
            require(parse_time(step['completed_at']) >= parse_time(step['started_at']), 'Invalid compile timestamps')
    require(compiled == row['observed_compile_attempts'], 'Historical actual-build accounting changed')
    require(row['ledger_import_allowed'] is False and row['automatic_retry_allowed'] is False,
            'Audit is not a worker-state/retry authorization')
    data = document(row)
    source_hint(row)
    if row['disposition'] == 'VERIFIED_LEGACY_SUCCESS_IDENTITY':
        identity(row)
    else:
        require(row['disposition'] in ('REVIEW_REQUIRED','NO_BUILD_REUSE','NO_BUILD_IDENTITY_REVIEW'),
                'Unknown migration disposition')
        require(row['coordinator_build_identity'] is None or row['disposition'] == 'NO_BUILD_REUSE',
                'Unknown identity cannot acquire a positive alias')
    return data


class Catalog:
    def __init__(self, records=()):
        records = copy.deepcopy(list(records))
        self._records = {}
        approved = audited_rows() if records else {}
        for record in records:
            require(set(record) == {'audit_row','observation'}, 'Unknown legacy record schema')
            row = record['audit_row']
            require(approved.get(row.get('run_id')) == row, 'Record is not the exact reviewed audit row')
            validate_observation(row, record['observation'])
            key = (row['channel'], row['run_id'])
            require(key not in self._records, 'Duplicate historical run')
            self._records[key] = record

    @property
    def records(self):
        return copy.deepcopy(self._records)

    def decision(self, build):
        matching = [v['audit_row'] for (c, _),v in self._records.items() if c == build.channel]
        if any(identity(r) == build or (identity(r) is not None and identity(r).key == build.key) for r in matching):
            return 'SUCCESS_HOLD'
        if any(identity(r) is None and source_hint(r) in ('', build.source.upstream_sha) for r in matching):
            return 'REVIEW_HOLD'
        return 'NO_OP'  # Never permission to reserve, retry, sign or publish.

    def blockers(self, build):
        decision = self.decision(build)
        rows = [v['audit_row'] for (channel, _),v in self._records.items() if channel == build.channel]
        if decision == 'SUCCESS_HOLD':
            return sorted(r['run_id'] for r in rows if identity(r) is not None and identity(r).key == build.key)
        if decision == 'REVIEW_HOLD':
            return sorted(r['run_id'] for r in rows if identity(r) is None
                          and source_hint(r) in ('',build.source.upstream_sha))
        return []

    def archived(self, run, channel):
        record = self._records.get((channel, run.get('id')))
        if record is None:
            return None
        require(fingerprint(run) == record['observation']['run'], 'Archived run provenance/attempt drift')
        return document(record['audit_row'])

    def historical_identity(self, run, channel):
        record = self._records.get((channel, run.get('id')))
        if record is None:
            return None
        require(fingerprint(run) == record['observation']['run'], 'Archived run provenance/attempt drift')
        result = identity(record['audit_row'])
        require(result is not None, 'Archived historical identity/producer requires review')
        return result

    def unrelated_source(self, run, channel, upstream_sha):
        record = self._records.get((channel, run.get('id')))
        if record is None:
            return False
        require(fingerprint(run) == record['observation']['run'], 'Archived run provenance/attempt drift')
        archived_sha = source_hint(record['audit_row'])
        return bool(archived_sha and archived_sha != upstream_sha)

    def annotate_nightly(self, run):
        record = self._records.get(('nightly', run.get('id')))
        if record is None:
            return False
        require(fingerprint(run) == record['observation']['run'], 'Archived run provenance/attempt drift')
        row = record['audit_row'];build = identity(row)
        run['_upstream_sha'] = source_hint(row)
        if build is None:
            run['_nightly_identity_unresolved'] = True
        else:
            run['_nightly_identity'] = build.historical_digest
        return True


def load(directory=CATALOG, *, pending_head=None):
    """Validate a single append-only content-addressed chain; forks fail closed."""
    directory = Path(directory)
    require(not directory.is_symlink() and not (directory/'objects').is_symlink(), 'Symlinked evidence directory')
    require(not (directory/'head.json').is_symlink(), 'Symlinked evidence head')
    raw_head = (directory/'head.json').read_bytes() if pending_head is None else pending_head
    head = json.loads(raw_head)
    require(canonical(head) == raw_head, 'Noncanonical evidence head')
    require(set(head) == {'schema_version','catalog_sha256'} and type(head['schema_version']) is int
            and head['schema_version'] == 1, 'Unknown legacy catalog head')
    hex_value(head['catalog_sha256'], 64)
    files = list((directory/'objects').glob('*.json'))
    require(0 < len(files) <= 100, 'Missing/oversized legacy catalog inventory')
    objects = {}
    for path in files:
        require(path.is_file() and not path.is_symlink(), 'Nonregular evidence object')
        key = path.stem;hex_value(key, 64);raw = path.read_bytes()
        require(len(raw) <= 2*1024*1024 and hashlib.sha256(raw).hexdigest() == key, 'Legacy object digest mismatch')
        value = json.loads(raw)
        require(canonical(value) == raw and set(value) == {'schema_version','kind','repository',
                'source_audit_sha256','previous_catalog_sha256','records'}
                and type(value['schema_version']) is int and value['schema_version'] == 1
                and value['kind'] == 'legacy-dedup-catalog' and value['repository'] == REPOSITORY
                and value['source_audit_sha256'] == AUDIT_SHA256, 'Unknown/unreviewed catalog schema/source')
        objects[key] = value
    require(head['catalog_sha256'] in objects, 'Legacy head object missing')
    visited = set();cursor = head['catalog_sha256'];child = None
    while cursor:
        require(cursor not in visited and cursor in objects, 'Legacy chain missing/cyclic')
        visited.add(cursor);value = objects[cursor];current = Catalog(value['records'])
        if child is not None:
            require(all(child.records.get(k) == v for k,v in current.records.items()), 'Legacy evidence cannot be removed or rewritten')
        child = current;cursor = value['previous_catalog_sha256']
        if cursor:hex_value(cursor, 64)
    require(visited == set(objects), 'Unmerged import fork or rolled-back legacy head')
    return Catalog(objects[head['catalog_sha256']]['records'])


def for_repository(repository):
    return load() if repository == REPOSITORY else Catalog()
