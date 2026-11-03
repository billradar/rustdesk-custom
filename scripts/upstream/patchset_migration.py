"""Read-only migration preflight. This does not authorize release cutover.

Legacy tags are identified by an audited inventory, never by their spelling.
The audit is historical evidence, not a replacement for live reconciliation.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / 'metadata/release/patchset-migration-audit.json'
LEGACY = 'legacy-per-upstream-release-allocation'
TAG = re.compile(r'v([0-9]+\.[0-9]+\.[0-9]+)-custom\.(v[1-9][0-9]*)\.([1-9][0-9]{0,5})')


def allocation(tag):
    match = TAG.fullmatch(tag)
    if match is None:
        raise ValueError('Invalid Stable tag: ' + tag)
    return match.group(1), match.group(2), int(match.group(3))


def legacy_names(audit):
    """Include Draft display names and archived observations, not just Git tags."""
    names = {row['name'] for row in audit['tags'] if row['semantics'] == LEGACY}
    names.update(row['name'] for row in audit['releases'] if not row['prerelease'])
    names.update(row['name'] for row in audit['historical_observations'])
    return names


def classify(tag, audit):
    # A matching regex alone cannot distinguish old release allocation from
    # content revision. An unknown tag must remain unknown after this audit.
    return LEGACY if tag in legacy_names(audit) else 'UNKNOWN_REQUIRES_EVIDENCE'


def validate(audit):
    if (audit.get('schema') != 'patchset-migration-audit-v1'
            or audit.get('repository') != 'billradar/rustdesk-custom'
            or audit.get('status') != 'BLOCKED'
            or audit.get('semantics') != LEGACY
            or not re.fullmatch('[0-9a-f]{40}', audit.get('baseline_main', ''))):
        raise ValueError('Invalid or prematurely activated migration audit')
    tags = audit['tags']
    if len({row['name'] for row in tags}) != len(tags):
        raise ValueError('Duplicate historical tag')
    for row in tags:
        if not re.fullmatch('[0-9a-f]{40}', row['commit']):
            raise ValueError('Historical tag must retain its exact peeled commit')
        if row['name'] != 'nightly':
            allocation(row['name'])
            if row['semantics'] != LEGACY:
                raise ValueError('Historical Stable tag semantic relabeling')
    ids = [row['id'] for row in audit['releases']]
    if any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Duplicate/invalid historical release ID')
    for row in audit['releases']:
        if not re.fullmatch('[0-9a-f]{64}', row['body_sha256']):
            raise ValueError('Missing historical body digest')
        if not row['prerelease']:
            _, generation, revision = allocation(row['name'])
            if row['metadata']['custom_release_revision'] != f'{generation}.{revision}':
                raise ValueError('Draft name and legacy metadata disagree')
        for key in ('common_patch_hash', 'sos_patch_hash'):
            if not re.fullmatch('[0-9a-f]{64}', row['metadata'][key]):
                raise ValueError('Missing historical patch identity')
    for generation, revision in audit['candidate_initial_revisions'].items():
        if (not re.fullmatch('v[1-9][0-9]*', generation)
                or type(revision) is not int or not 1 <= revision <= 999999):
            raise ValueError('Invalid candidate initial revision')
        consumed = [allocation(name)[2] for name in legacy_names(audit)
                    if allocation(name)[1] == generation]
        if revision <= max(consumed, default=0):
            raise ValueError('Candidate revision does not exceed observed legacy allocation')
    required = {'COORDINATOR_REVISION_IDENTITY', 'BUILD_POLICY_IDENTITY', 'ACTIVE_WORKERS',
                'INCOMPLETE_HISTORICAL_ALLOCATION', 'CUTOVER_NOT_COMMITTED'}
    if set(audit['activation_blockers']) != required:
        raise ValueError('Audit blockers require a separate reviewed cutover contract')
    return audit


def target_available(upstream, generation, revision, audit):
    """Offline collision check only; live Tag/Draft/Release checks remain mandatory."""
    tag = f'v{upstream}-custom.{generation}.{revision}'
    allocation(tag)
    if tag in legacy_names(audit):
        raise ValueError('Historical Tag/Draft/allocation is immutable: ' + tag)
    return tag


def identity_gaps():
    """Exercise the current shared identity, rather than infer it from filenames."""
    from scripts.release.coordinator.identity import BuildIdentity, SourceIdentity
    source = SourceIdentity('a' * 40, 'v2', 'b' * 64, 'c' * 64)
    # Revision N and N+2 after a content reversion have exactly the same v1
    # source and build keys. Neither schema accepts a revision/policy digest.
    fields = set(SourceIdentity.__dataclass_fields__)
    build_fields = set(BuildIdentity.__dataclass_fields__)
    return dict(
        source_binds_revision='patchset_revision' in fields,
        build_binds_policy_digest='build_policy_sha256' in build_fields,
        example_source_key=source.key,
        example_stable_key=BuildIdentity('stable', source, False, '', False).key,
        example_nightly_key=BuildIdentity('nightly', source, False, '', False).key,
    )


def report(audit):
    validate(audit)
    return dict(schema='patchset-migration-preflight-v1', status='BLOCKED',
                release_cutover_allowed=False, observation_only=True,
                baseline_main=audit['baseline_main'],
                candidate_initial_revisions=audit['candidate_initial_revisions'],
                candidates_are_not_assigned_versions=True,
                blockers=audit['activation_blockers'], identity=identity_gaps(),
                legacy_versions=sorted(legacy_names(audit)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=AUDIT)
    parser.add_argument('--check', action='store_true', help='Exit 1 while cutover is blocked')
    args = parser.parse_args()
    try:
        result = report(json.loads(args.audit.read_text()))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps(dict(status='INVALID', error=str(error)), sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if args.check else 0


if __name__ == '__main__':
    raise SystemExit(main())
