"""Small, shared dedup identity: official upstream SHA plus patchset SHA-256.

This identity is a routing hint, not a substitute for release/signing gates.
"""
import hashlib
import re


def _hex(value, n):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{%d}' % n, value):
        raise ValueError('Invalid Coordinator Lite SHA')


def patchset_sha256(common_sha256, sos_sha256):
    """Hash both patch families; neither branding nor build options are inputs."""
    _hex(common_sha256, 64)
    _hex(sos_sha256, 64)
    return hashlib.sha256(b'patchset-v1\0' +
                          bytes.fromhex(common_sha256) + bytes.fromhex(sos_sha256)).hexdigest()


def build_identity(upstream_sha, patchset_sha):
    _hex(upstream_sha, 40)
    _hex(patchset_sha, 64)
    return hashlib.sha256(b'build-v1\0' +
                          bytes.fromhex(upstream_sha) + bytes.fromhex(patchset_sha)).hexdigest()


def from_hashes(upstream_sha, common_sha256, sos_sha256):
    return build_identity(upstream_sha, patchset_sha256(common_sha256, sos_sha256))


def matching_state(rows):
    """Any unresolved or active matching run blocks duplicate dispatch."""
    if any(row.get('status') != 'completed' for row in rows):
        return 'ACTIVE'
    if any(row.get('conclusion') == 'success' for row in rows):
        return 'SUCCESS'
    return 'RETRY'


def verify_worker_context(env=None):
    """Fail closed on a foreign root workflow without requiring the retired ledger.

    The trusted root resolve job performs Lite dedup before reusable workers can
    start. This check verifies GitHub's immutable workflow-run context only;
    exact prepared-source and artifact gates remain separate and mandatory.
    No extra values enter the upstream+patchset build identity.
    """
    import os

    values = os.environ if env is None else env
    workflows = {
        'nightly': ('nightly.yml', 'Nightly Build Pipeline'),
        'stable': ('tag.yml', 'Stable Release Pipeline'),
    }
    channel = values.get('BUILD_CHANNEL', '')
    if channel not in workflows:
        raise ValueError('Unsupported Coordinator Lite build channel')
    repo = values.get('GITHUB_REPOSITORY', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid worker repository')
    file, name = workflows[channel]
    if (values.get('GITHUB_REF') != 'refs/heads/main'
            or values.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or values.get('GITHUB_WORKFLOW') != name
            or values.get('GITHUB_WORKFLOW_REF')
            != f'{repo}/.github/workflows/{file}@refs/heads/main'):
        raise ValueError('Untrusted Coordinator Lite worker workflow')
    _hex(values.get('GITHUB_SHA'), 40)
    _hex(values.get('UPSTREAM_EXPECTED_SHA'), 40)
    if not re.fullmatch(r'v[1-9][0-9]*', values.get('PATCHSET', '')):
        raise ValueError('Invalid worker patchset')
    for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        if not re.fullmatch(r'[1-9][0-9]*', values.get(key, '')):
            raise ValueError('Invalid worker run identity')


if __name__ == '__main__':
    import sys

    if sys.argv[1:] != ['worker-guard']:
        raise SystemExit('Usage: python -m scripts.release.coordinator_lite worker-guard')
    verify_worker_context()
    print('Coordinator Lite worker context: PASS (root resolve owns dedup)')
