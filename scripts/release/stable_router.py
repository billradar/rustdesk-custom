#!/usr/bin/env python3
"""Route the latest official Stable release to a complete private Draft build."""
import os
import re
import subprocess

from scripts.release.channel import release_preflight
from scripts.upstream.patchsets import patchset_for_version
from scripts.upstream.resolve import api, choose_stable

REPOSITORY = 'billradar/rustdesk-custom'
WORKFLOW = 'tag.yml'
MAX_ATTEMPTS = 3


def verify_context():
    """Only allow scheduled/manual routing from the trusted main branch."""
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise ValueError('Stable router may only run in the release repository')
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Stable router may only dispatch from main')
    if os.environ.get('GITHUB_EVENT_NAME') not in ('schedule', 'workflow_dispatch'):
        raise ValueError('Unsupported Stable router trigger')
    if not re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', '')):
        raise ValueError('Stable router requires an exact custom repository SHA')


def discovery():
    release = choose_stable()
    data = {
        'channel': 'stable',
        'upstream_tag': release['upstream_tag'],
        'upstream_ref': release['upstream_tag'],
        'upstream_sha': release['upstream_sha'],
        'version': release['version'],
        'patchset': patchset_for_version(release['version']),
    }
    return data


def existing_build(data):
    """Use the downstream release gate as the sole authority for reuse."""
    os.environ['INCLUDE_WAYLAND'] = 'true'
    return not release_preflight(data)['build_needed']


def workflow_runs(tag, custom_sha):
    """Find prior exact tag.yml dispatches for this complete source identity."""
    runs = []
    for page in range(1, 11):
        batch = api(f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?branch=main&event=workflow_dispatch&per_page=100&page={page}') or {}
        runs.extend(batch.get('workflow_runs', []))
        if len(batch.get('workflow_runs', [])) < 100:
            return [row for row in runs if row.get('head_branch') == 'main'
                    and row.get('event') == 'workflow_dispatch'
                    and row.get('head_sha') == custom_sha
                    and row.get('display_title') in (
                        f'Stable {tag} / draft / wayland=true',
                        # Older router runs did not include Wayland in run-name.
                        f'Stable {tag} / draft',
                    )]
    raise ValueError('Stable workflow run history exceeds lookup limit; manual review required')


def run_state(rows):
    if any(row.get('status') != 'completed' for row in rows):
        return 'ACTIVE'
    return 'EXHAUSTED' if len(rows) >= MAX_ATTEMPTS else 'RETRY'


def dispatch(tag):
    subprocess.run([
        'gh', 'workflow', 'run', WORKFLOW,
        '--repo', REPOSITORY,
        '--ref', 'main',
        '-f', f'upstream_ref={tag}',
        '-f', 'release_mode=draft',
        '-f', 'include_wayland=true',
    ], check=True)


def route():
    verify_context()
    data = discovery()
    if existing_build(data):
        print(f"Complete Stable build already exists for {data['upstream_tag']}; skip.")
        return

    state = run_state(workflow_runs(data['upstream_tag'], os.environ['GITHUB_SHA']))
    if state == 'ACTIVE':
        print(f"A Stable Draft build is already active for {data['upstream_tag']}; skip.")
        return
    if state == 'EXHAUSTED':
        raise ValueError('Stable Draft retry budget exhausted; manual review required')

    dispatch(data['upstream_tag'])
    print(f"Dispatched Stable Draft build for {data['upstream_tag']}.")


if __name__ == '__main__':
    route()
