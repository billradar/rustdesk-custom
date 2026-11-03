"""Read-only GitHub evidence verifier for a reviewed Content Identity v2 cutover.

Never activates cutover. Any missing, ambiguous or changed API observation fails closed.
"""
import argparse
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = 'billradar/rustdesk-custom'
SHA40 = re.compile(r'[0-9a-f]{40}\\Z')
SHA64 = re.compile(r'[0-9a-f]{64}\\Z')
JOURNAL_PREFIX = 'refs/heads/release-coordinator/v1/'
REQUIRED_RUNS = {
    'Patchset content version contract',
    'CI - Patch and Build compatibility',
    'Coordinator cutover offline contracts',
}


def fail(message):
    raise ValueError('ACTIVATION_EVIDENCE_INVALID: ' + message)


def valid_sha(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def github_get(path, token):
    if not token:
        fail('GITHUB_TOKEN is required for authenticated repository evidence')
    request = Request('https://api.github.com/repos/' + REPOSITORY + '/' + path,
                      headers={'Authorization': 'Bearer ' + token,
                               'Accept': 'application/vnd.github+json',
                               'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        fail('GitHub API read failed: ' + str(error))


def verify(evidence, get):
    if not isinstance(evidence, dict) or set(evidence) != {
            'main_sha', 'successful_run_ids', 'journal_heads', 'release_ids'}:
        fail('unexpected or missing evidence fields')
    sha = evidence['main_sha']
    if not valid_sha(sha, SHA40):
        fail('invalid main SHA')
    main = get('git/ref/heads/main')
    if (main.get('ref') != 'refs/heads/main'
            or main.get('object', {}).get('sha') != sha):
        fail('main branch changed since evidence capture')

    runs = evidence['successful_run_ids']
    if (not isinstance(runs, list) or len(runs) < 3
            or any(type(i) is not int or i <= 0 for i in runs)
            or len(set(runs)) != len(runs)):
        fail('invalid run inventory')
    names = set()
    for run_id in runs:
        run = get('actions/runs/' + str(run_id))
        if (run.get('id') != run_id or run.get('head_sha') != sha
                or run.get('status') != 'completed' or run.get('conclusion') != 'success'
                or run.get('repository', {}).get('full_name') != REPOSITORY
                or run.get('event') not in ('push', 'workflow_run')):
            fail('unverified successful run: ' + str(run_id))
        names.add(run.get('name'))
    if not REQUIRED_RUNS.issubset(names):
        fail('missing required main-branch workflow gates')

    heads = evidence['journal_heads']
    if (not isinstance(heads, dict) or len(heads) < 2
            or any(not valid_sha(k, SHA64) or not valid_sha(v, SHA40)
                   for k, v in heads.items())):
        fail('invalid journal inventory')
    refs = get('git/matching-refs/heads/release-coordinator/v1/')
    actual = {}
    for ref in refs:
        name = ref.get('ref', '')
        if not name.startswith(JOURNAL_PREFIX):
            fail('unexpected journal ref')
        key = name[len(JOURNAL_PREFIX):].split('/')
        if len(key) != 2 or key[0] not in ('stable', 'nightly') or not valid_sha(key[1], SHA64):
            fail('invalid journal ref')
        if ref.get('object', {}).get('type') != 'commit':
            fail('journal is not a commit')
        actual[key[1]] = ref['object'].get('sha')
    if actual != heads:
        fail('journal inventory changed or incomplete')

    releases = evidence['release_ids']
    if (not isinstance(releases, list) or len(releases) < 3
            or any(type(i) is not int or i <= 0 for i in releases)
            or len(set(releases)) != len(releases)):
        fail('invalid release inventory')
    all_releases = get('releases?per_page=100')
    if not isinstance(all_releases, list) or len(all_releases) >= 100:
        fail('release inventory is incomplete or malformed')
    actual_releases = {r.get('id') for r in all_releases}
    if actual_releases != set(releases):
        fail('release inventory changed')
    for release_id in releases:
        item = get('releases/' + str(release_id))
        if (item.get('id') != release_id or item.get('draft') is not True
                or item.get('published_at') is not None
                or not isinstance(item.get('assets'), list)
                or len(item['assets']) != 32):
            fail('release draft or assets changed: ' + str(release_id))
    for status in ('in_progress', 'queued', 'waiting'):
        queue = get('actions/runs?status=' + status + '&per_page=1')
        if type(queue.get('total_count')) is not int or queue['total_count'] != 0:
            fail('GitHub Actions is not quiescent: ' + status)
    return {'decision': 'EVIDENCE_VERIFIED_NOT_ACTIVATED', 'repository': REPOSITORY,
            'main_sha': sha, 'run_ids': runs, 'journal_heads': heads,
            'release_ids': releases}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', help='JSON with main_sha, successful_run_ids, journal_heads, release_ids')
    args = parser.parse_args()
    with open(args.evidence, encoding='utf-8') as stream:
        evidence = json.load(stream)
    result = verify(evidence, lambda path: github_get(path, os.environ.get('GITHUB_TOKEN')))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
