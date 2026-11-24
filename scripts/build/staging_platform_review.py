"""Non-approving exact-source platform interface comparison for v4 staging."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.platform.platform_adapter import FILES, inspect, ROOT

SOURCES = {
    'old': '6aec3069aec486ad7df07429a0a1ee411fc8d73a',
    'candidate': '9724512429b053be04cdb843345e99ddcccdb80e',
    'current': '51f94394ce61e1f3d26229565c326b2862cbdd1f',
}
ARCHES = {
    'windows': ('x86_64',),
    'android': ('aarch64', 'armv7', 'x86_64'),
    'macos': ('x86_64', 'aarch64'),
}
ANDROID_FILES = (
    'flutter/build_android_deps.sh', 'flutter/ndk_arm64.sh',
    'flutter/ndk_arm.sh', 'flutter/ndk_x64.sh',
    'flutter/android/app/build.gradle',
)

def sha256(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()

def review(platform, root):
    registry = json.loads((ROOT / 'metadata/platform/adapter-profiles.json').read_text())
    rows = {}
    for label, expected in SOURCES.items():
        tree = root / label
        actual = subprocess.check_output(
            ['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != expected:
            raise ValueError(f'Unexpected official source {actual}, wanted {expected}')
        for arch in ARCHES[platform]:
            profile, job = inspect(tree, platform, arch)
            if profile['official_disabled']:
                raise ValueError(f'Official {platform}/{arch} job disabled')
            files = tuple(FILES) + (ANDROID_FILES if platform == 'android' else ())
            rows[label, arch] = {
                'source_sha': actual,
                'signature': profile['signature'],
                'runner': profile['runner'],
                'upstream_runner': profile['upstream_runner'],
                'target': profile['target'],
                'triplet': profile['triplet'],
                'rust': profile['rust'],
                'flutter': profile['flutter'],
                'vcpkg': profile['vcpkg'],
                'ndk': profile['ndk'],
                'cargo_ndk': profile['cargo_ndk'],
                'cmake': profile['cmake'],
                'approved_signature_present': profile['signature'] in registry['approved'].get(platform, []),
                'file_hashes': {p: sha256(tree / p) for p in files},
                'job': json.loads(json.dumps(job)),
                'tools': profile['tools'],
            }
    result = []
    for arch in ARCHES[platform]:
        old, candidate, current = (rows[label, arch] for label in SOURCES)
        result.append({
            'platform': platform, 'architecture': arch,
            'old': old, 'candidate': candidate, 'current': current,
            'job_unchanged_from_old': old['job'] == current['job'],
            'tools_unchanged_from_old': old['tools'] == current['tools'],
            'candidate_and_current_signatures_equal': candidate['signature'] == current['signature'],
            'changed_files_from_old': [
                f for f in old['file_hashes'] if old['file_hashes'][f] != current['file_hashes'][f]
            ],
            'decision': 'HOLD: exact source review and native CI fixture build required; no release approval',
        })
    return {'kind': 'static-platform-interface-review', 'release_approval_granted': False,
            'native_build_executed': False, 'platform': platform, 'targets': result}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('platform', choices=ARCHES)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    report = review(args.platform, args.root)
    output = args.root / 'reports' / (args.platform + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    for row in report['targets']:
        print(json.dumps({k: v for k, v in row.items() if k not in SOURCES} |
                         {'source_sha': row['current']['source_sha'],
                          'signature': row['current']['signature'],
                          'runner': row['current']['runner']}, sort_keys=True))
    print('Static interface evidence collected; no native build or release approval.')

if __name__ == '__main__':
    main()
