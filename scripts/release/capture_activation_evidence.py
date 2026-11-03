"""Capture live, immutable-by-run GitHub evidence without committing a stale main SHA."""
import json
import os
from pathlib import Path
from scripts.release.verify_activation_evidence import github_get, fail, REQUIRED_RUNS, JOURNAL_PREFIX, SHA64, valid_sha

def capture(get, own_run):
    main = get('git/ref/heads/main')['object']['sha']
    results = get('actions/runs?head_sha=' + main + '&per_page=100')
    if results.get('total_count', 0) >= 100:
        fail('incomplete run inventory')
    runs = results.get('workflow_runs', [])
    ids = []
    for name in sorted(REQUIRED_RUNS | {'Build reliability and targeted recovery'}):
        matches = [r for r in runs if r.get('name') == name
                   and r.get('head_sha') == main
                   and r.get('status') == 'completed'
                   and r.get('conclusion') == 'success'
                   and r.get('event') in ('push', 'workflow_run')]
        if not matches:
            fail('missing successful current-main workflow: ' + name)
        ids.append(max(r['id'] for r in matches))
    refs = get('git/matching-refs/heads/release-coordinator/v1/')
    heads = {}
    for ref in refs:
        parts = ref.get('ref', '').removeprefix(JOURNAL_PREFIX).split('/')
        if len(parts) != 2 or parts[0] not in ('stable', 'nightly') or not valid_sha(parts[1], SHA64):
            fail('unexpected journal reference')
        heads[parts[1]] = ref['object']['sha']
    releases = get('releases?per_page=100')
    if len(releases) >= 100:
        fail('incomplete release inventory')
    return dict(main_sha=main, successful_run_ids=ids,
                journal_heads=heads, release_ids=[r['id'] for r in releases])

def main():
    token = os.environ.get('GITHUB_TOKEN')
    get = lambda path: github_get(path, token)
    data = capture(get, os.environ.get('GITHUB_RUN_ID'))
    target = Path('content-v2-live-evidence.json')
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    print('Captured live evidence for main ' + data['main_sha'])
    print('Evidence path: ' + str(target))

if __name__ == '__main__':
    main()
