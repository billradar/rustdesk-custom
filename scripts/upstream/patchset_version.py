"""Version-controlled Patchset content revisions; offline, base-anchored allocation."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'patchset-content-v1'
CATEGORIES = ('Added', 'Changed', 'Fixed', 'Removed', 'Security', 'Compatibility')
FOLDERS = ('common', 'sos')


def git(*args, root=ROOT):
    return subprocess.check_output(['git', *args], cwd=root)


def commit(ref, root=ROOT):
    return git('rev-parse', '--verify', '--end-of-options', ref + '^{commit}', root=root).decode().strip()


def manifest(name, root=ROOT, ref=None):
    if not re.fullmatch(r'v[1-9][0-9]*', name):
        raise ValueError('Invalid patchset')
    path = f'patchsets/{name}/patchset.json'
    return json.loads(git('show', f'{ref}:{path}', root=root) if ref else (root / path).read_bytes())


def hashes(name, root=ROOT, ref=None):
    result = {}
    for folder in FOLDERS:
        prefix = f'patchsets/{name}/{folder}/'
        if ref:
            rows = git('ls-tree', '-r', '-z', ref, '--', prefix, root=root).split(b'\0')
            paths = []
            for row in filter(None, rows):
                info, path = row.split(b'\t', 1)
                path = path.decode()
                if path.endswith('.patch') and '/' not in path[len(prefix):]:
                    if not info.startswith(b'100644 blob '):
                        raise ValueError('Patch must be a regular file')
                    paths.append((Path(path).name, git('show', f'{ref}:{path}', root=root)))
        else:
            files = sorted((root / prefix).glob('*.patch'))
            if any(p.is_symlink() or not p.is_file() for p in files):
                raise ValueError('Patch must be a regular file')
            paths = [(p.name, p.read_bytes()) for p in files]
        if not paths:
            raise ValueError('Empty patch generation')
        digest = hashlib.sha256()
        for filename, raw in sorted(paths):
            digest.update(filename.encode() + b'\0' + raw.replace(b'\r\n', b'\n'))
        result[folder] = digest.hexdigest()
    return result


def text(value):
    if (not isinstance(value, str) or not value.strip()
            or re.search(r'\b(TODO|TBD|PLACEHOLDER)\b', value, re.I)):
        raise ValueError('Changelog requires reviewed non-placeholder text')


def validate(data, actual):
    versioning = data['versioning']
    if versioning['schema'] != SCHEMA or data['hashes'] != actual:
        raise ValueError('Patch metadata/content hash mismatch')
    initial = versioning['initial_revision']
    history = versioning['history']
    if type(initial) is not int or initial < 1 or not history:
        raise ValueError('Missing version history')
    previous = None
    for index, entry in enumerate(history):
        if (type(entry['revision']) is not int or entry['revision'] != initial + index
                or entry['revision'] > 999999 or entry['review_status'] != 'reviewed'):
            raise ValueError('Revision history must be sequential and reviewed')
        if set(entry['after']) != set(FOLDERS) or set(entry['before']) != set(FOLDERS):
            raise ValueError('Changelog requires both before/after patch hashes')
        for value in list(entry['after'].values()) + list(entry['before'].values()):
            if not re.fullmatch('[0-9a-f]{64}', value):
                raise ValueError('Invalid historical patch hash')
        changed = [f for f in FOLDERS if entry['before'][f] != entry['after'][f]]
        if index == 0:
            if entry['kind'] != 'migration-baseline' or entry['before'] != entry['after']:
                raise ValueError('Initial entry must describe a migration baseline')
        elif (entry['kind'] != 'content-change' or entry['before'] != previous
              or not changed or entry['scopes'] != changed):
            raise ValueError('Changelog/hash chain mismatch')
        if not entry['scopes'] or any(f not in FOLDERS for f in entry['scopes']):
            raise ValueError('Missing Common/SOS scope')
        if set(entry['categories']) != set(CATEGORIES) or not any(entry['categories'].values()):
            raise ValueError('Missing changelog categories')
        for items in entry['categories'].values():
            if not isinstance(items, list):
                raise ValueError('Category must be a list')
            for item in items:
                text(item)
        for key in ('reason', 'compatibility', 'limitations'):
            text(entry[key])
        if not entry['references'] or not all(re.fullmatch(r'[0-9a-f]{40}|https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:pull/[1-9][0-9]*|commit/[0-9a-f]{40})', x) for x in entry['references']):
            raise ValueError('Changelog requires a PR or commit reference')
        if not re.fullmatch('[0-9a-f]{40}', entry['base_sha']):
            raise ValueError('Missing allocation base SHA')
        previous = entry['after']
    if type(data['revision']) is not int or data['revision'] != history[-1]['revision'] or actual != previous:
        raise ValueError('Current revision does not match history')
    for folder in FOLDERS:
        if not versioning['features'][folder]:
            raise ValueError('Missing current feature inventory')
        for item in versioning['features'][folder]:
            text(item)
    return data


def render(data):
    lines = [f'# Patchset {data["id"]} changelog', '',
             'Content revisions are independent of RustDesk versions. Legacy release allocations retain their original semantics.', '',
             '## Current included features', '']
    for folder in FOLDERS:
        lines += [f'### {folder.title()}', ''] + ['- ' + x for x in data['versioning']['features'][folder]] + ['']
    lines += ['## Revision history', '']
    for entry in reversed(data['versioning']['history']):
        lines += [f'### {data["id"]}.{entry["revision"]} — {entry["kind"]}', '',
                  'Scope: ' + ', '.join(entry['scopes']), '', 'Reason: ' + entry['reason'], '']
        for category in CATEGORIES:
            lines += [f'#### {category}', ''] + ['- ' + x for x in entry['categories'][category]] + ['']
        lines += ['References: ' + ', '.join(entry['references']), '',
                  'Upstream compatibility: ' + entry['compatibility'], '',
                  'Known limitations: ' + entry['limitations'], '',
                  'Allocation base: `' + entry['base_sha'] + '`', '']
        for folder in FOLDERS:
            lines += [f'- {folder}: `{entry["before"][folder]}` → `{entry["after"][folder]}`']
        lines += ['']
    return '\n'.join(lines)


def current(name, root=ROOT):
    data = validate(manifest(name, root), hashes(name, root))
    path = root / f'patchsets/{name}/CHANGELOG.md'
    if path.is_symlink() or not path.is_file() or path.read_text() != render(data):
        raise ValueError('Missing or stale generated Changelog: ' + name)
    return data


def verify(name, base='origin/main', root=ROOT):
    base_sha = commit(base, root)
    # Do not accept merge-base verification against an obsolete base branch.
    subprocess.run(['git', 'merge-base', '--is-ancestor', base_sha, 'HEAD'], cwd=root, check=True)
    data = current(name, root)
    existing = git('ls-tree', '--name-only', base_sha, '--',
                   f'patchsets/{name}', root=root).decode().strip()
    if not existing:
        # A new generation gets one base-anchored content baseline. It cannot
        # rewrite an existing generation or inherit its release eligibility.
        history = data['versioning']['history']
        parent = data.get('derived_from', {})
        origin = manifest(parent.get('patchset', ''), root, base_sha)
        validate(origin, hashes(parent['patchset'], root, base_sha))
        if (data['id'] != name or data['revision'] != 1 or len(history) != 1
                or data['versioning']['initial_revision'] != 1
                or data['versioning']['migration_base'] != base_sha
                or history[0]['base_sha'] != base_sha
                or parent.get('revision') != origin['revision']
                or parent.get('hashes') != origin['hashes']
                or data.get('status') != 'candidate_only'):
            raise ValueError('New Patchset requires an isolated candidate baseline anchored to its parent')
        return dict(patchset=name, patchset_version=f'{name}.1', base_sha=base_sha,
                    content_changed=True, hashes=data['hashes'], result='PASS')
    old = manifest(name, root, base_sha)
    before, after = hashes(name, root, base_sha), hashes(name, root)
    if 'versioning' not in old:
        raise ValueError('Unversioned Patchset base is retired; rebase onto a reviewed versioned main')
    else:
        validate(old, before)
        for key in ('schema', 'initial_revision', 'migration_base'):
            if data['versioning'][key] != old['versioning'][key]:
                raise ValueError('Immutable migration identity changed')
        changed = before != after
        expected = old['revision'] + int(changed)
        if data['revision'] != expected:
            raise ValueError(f'Expected revision {expected}, got {data["revision"]}; recompute against latest base')
        history = data['versioning']['history']
        previous = old['versioning']['history']
        if history[:len(previous)] != previous or len(history) != len(previous) + int(changed):
            raise ValueError('Historical revision identity changed')
        if changed and (history[-1]['base_sha'] != base_sha or history[-1]['before'] != before):
            raise ValueError('Stale concurrent allocation; rebase and bump against latest base')
    return dict(patchset=name, patchset_version=f'{name}.{data["revision"]}', base_sha=base_sha,
                content_changed=before != after, hashes=after, result='PASS')


def bump(name, base='origin/main', check=False, root=ROOT):
    base_sha = commit(base, root)
    subprocess.run(['git', 'merge-base', '--is-ancestor', base_sha, 'HEAD'], cwd=root, check=True)
    old = manifest(name, root, base_sha)
    validate(old, hashes(name, root, base_sha))
    data = manifest(name, root)
    after = hashes(name, root)
    if after == old['hashes']:
        raise ValueError('No patch content change; revision must not increase')
    if data['versioning']['history'][:len(old['versioning']['history'])] != old['versioning']['history']:
        raise ValueError('Historical revision identity changed')
    revision = old['revision'] + 1
    existing = data['versioning']['history'][len(old['versioning']['history']):]
    # An already edited template is retained only if its exact hash identity and
    # allocation base still agree. New patch edits require fresh semantic review.
    entry = dict(revision=revision, kind='content-change', base_sha=base_sha,
                 before=old['hashes'], after=after,
                 scopes=[f for f in FOLDERS if old['hashes'][f] != after[f]],
                 categories={c: [] for c in CATEGORIES}, reason='TODO: explain actual change and reason',
                 references=[], compatibility='TODO: review upstream compatibility',
                 limitations='TODO: record known limitations', review_status='pending')
    if len(existing) == 1 and all(existing[0].get(k) == entry[k] for k in ('revision','base_sha','before','after','scopes')):
        entry = existing[0]
    data.update(revision=revision, hashes=after)
    data['versioning']['history'] = copy.deepcopy(old['versioning']['history']) + [entry]
    result = dict(patchset=name, patchset_version=f'{name}.{revision}', base_sha=base_sha,
                  hashes=after, written=not check, review_status=entry['review_status'])
    if not check:
        (root / f'patchsets/{name}/patchset.json').write_text(json.dumps(data, indent=2) + '\n')
        (root / f'patchsets/{name}/CHANGELOG.md').write_text(render(data))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('bump', 'verify', 'render'))
    parser.add_argument('--patchset')
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        names = [args.patchset] if args.patchset else sorted(p.parent.name for p in (ROOT / 'patchsets').glob('v*/patchset.json'))
        if args.mode == 'bump' and not args.patchset:
            raise ValueError('bump requires --patchset')
        results = []
        for name in names:
            if args.mode == 'verify':
                results.append(verify(name, args.base))
            elif args.mode == 'bump':
                results.append(bump(name, args.base, args.check))
            else:
                data = validate(manifest(name), hashes(name))
                target = ROOT / f'patchsets/{name}/CHANGELOG.md'
                if args.check:
                    current(name)
                else:
                    target.write_text(render(data))
                results.append(dict(patchset=name, result='PASS'))
        print(json.dumps(dict(result='PASS', patchsets=results), sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps(dict(result='FAIL', error=str(error)), sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
