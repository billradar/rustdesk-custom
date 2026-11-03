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

def verify_worker_context():
    """Check the trusted caller without the retired Coordinator journal.

    This is a stateless workflow-origin check, not build admission or a
    deduplication key. Prepared-source, package and signing gates remain
    responsible for verifying their own immutable inputs.
    """
    import os

    workflows = {'nightly': 'nightly.yml', 'stable': 'tag.yml'}
    channel = os.environ.get('BUILD_CHANNEL')
    workflow = workflows.get(channel)
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not workflow or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Untrusted Coordinator Lite worker channel or repository')
    expected = f'{repo}/.github/workflows/{workflow}@refs/heads/main'
    if (os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_WORKFLOW_REF') != expected):
        raise ValueError('Untrusted Coordinator Lite worker caller')
    _hex(os.environ.get('GITHUB_SHA'), 40)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('verify-worker',))
    parser.parse_args()
    verify_worker_context()
