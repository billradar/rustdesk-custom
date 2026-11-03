#!/usr/bin/env python3
"""Freeze Stable identity once, then require it at preflight and artifact gates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from scripts.release import channel
from scripts.upstream.patchsets import patchset_for_version, verify, patch_hash

SCHEMA = 'stable-build-lock-v1'


def boolean(name):
    value = os.environ.get(name, 'false')
    if value not in ('true', 'false'):
        raise ValueError('Invalid locked option: ' + name)
    return value == 'true'


def plan(data, patchset):
    sha, version = data.get('upstream_sha', ''), data.get('version', '')
    tag = data.get('upstream_tag', '')
    if (data.get('channel') != 'stable' or not re.fullmatch('[0-9a-f]{40}', sha)
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)
            or tag not in (version, 'v' + version) or data.get('upstream_ref') != tag):
        raise ValueError('Invalid Stable discovery for identity lock')
    if patchset != patchset_for_version(version):
        raise ValueError('Locked patchset differs from explicit version selection')
    verify(patchset)
    custom = os.environ.get('GITHUB_SHA', '')
    run = os.environ.get('GITHUB_RUN_ID', '')
    if not re.fullmatch('[0-9a-f]{40}', custom) or not re.fullmatch('[1-9][0-9]*', run):
        raise ValueError('Stable lock requires exact custom commit and workflow run')
    included = boolean('INCLUDE_WAYLAND')
    signing = boolean('ANDROID_PRODUCTION_SIGNING_ENABLED')
    _, policy = channel.wayland_identity()
    common, sos = patch_hash('common', patchset), patch_hash('sos', patchset)
    identity = channel.build_identity(sha, patchset, common, sos,
                                     wayland_included=included, wayland_policy_sha256=policy,
                                     android_signing_enabled=signing)
    return dict(schema=SCHEMA, channel='stable', version=version, upstream_sha=sha,
                upstream_ref=tag, upstream_tag=tag, patchset=patchset,
                custom_repository_sha=custom, workflow_run=run,
                common_patch_hash=common, sos_patch_hash=sos,
                wayland_included=included, wayland_policy_sha256=policy,
                android_signing_enabled=signing, build_identity=identity)


def create(data, patchset, output):
    lock = plan(data, patchset)
    raw = (json.dumps(lock, indent=2, sort_keys=True) + '\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    if not re.fullmatch('[1-9][0-9]*', attempt):
        raise ValueError('Invalid workflow attempt')
    result = dict(lock, lock_sha256=digest,
                  lock_artifact=f'stable-build-lock-{lock["workflow_run"]}-{attempt}',
                  signing_enabled=str(lock['android_signing_enabled']).lower())
    from scripts.validation.summary import publish, stable_lock_card
    publish('stable-lock', stable_lock_card, lock)
    return result


def read(path, digest, identity):
    if not re.fullmatch('[0-9a-f]{64}', digest or '') or not re.fullmatch('[0-9a-f]{64}', identity or ''):
        raise ValueError('Mandatory Stable lock digest/build identity missing')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Stable lock artifact digest mismatch')
    lock = json.loads(raw)
    if (lock.get('schema') != SCHEMA or lock.get('build_identity') != identity
            or type(lock.get('wayland_included')) is not bool
            or type(lock.get('android_signing_enabled')) is not bool):
        raise ValueError('Stable lock schema/build identity mismatch')
    if lock != plan(lock, lock.get('patchset', '')):
        raise ValueError('Stable lock no longer matches this run, source or options')
    return lock


def current():
    return read(Path(os.environ.get('STABLE_LOCK_PATH', '')),
                os.environ.get('STABLE_LOCK_SHA256', ''), os.environ.get('EXPECTED_BUILD_IDENTITY', ''))


def require(infos=None):
    # General offline qualification remains usable; every Tag gate enables this.
    if os.environ.get('STABLE_LOCK_REQUIRED') != 'true':
        return None
    lock = current()
    if infos is not None:
        if {i.get('variant') for i in infos} != {'standard', 'sos'}:
            raise ValueError('Stable lock requires both source variants')
        for info in infos:
            for key, value in dict(upstream_sha=lock['upstream_sha'], upstream_version=lock['version'],
                                   patchset=lock['patchset'], common_patch_hash=lock['common_patch_hash'],
                                   custom_repository_sha=lock['custom_repository_sha'],
                                   build_run=lock['workflow_run']).items():
                if str(info.get(key)) != str(value):
                    raise ValueError('Built artifact differs from locked Stable input: ' + key)
            expected = lock['sos_patch_hash'] if info['variant'] == 'sos' else None
            if info.get('sos_patch_hash') != expected:
                raise ValueError('Built artifact differs from locked SOS identity')
    return lock


def preflight():
    lock = current()
    result = channel.release_preflight(dict(lock))
    if result.get('build_identity') != lock['build_identity']:
        raise ValueError('Stable preflight identity differs from resolved lock')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['create', 'preflight'])
    parser.add_argument('--discovery', type=Path)
    parser.add_argument('--patchset')
    parser.add_argument('--output', type=Path, default=Path('.work/stable-lock.json'))
    args = parser.parse_args()
    if args.mode == 'create':
        if args.discovery is None or not args.patchset:
            parser.error('create requires discovery and patchset')
        result = create(json.loads(args.discovery.read_text()), args.patchset, args.output)
    else:
        result = preflight()
    channel.outputs(result)


if __name__ == '__main__':
    main()
