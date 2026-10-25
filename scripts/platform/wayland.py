#!/usr/bin/env python3
"""Reviewed DRM recipes and same-run pair qualification for Tag/Nightly parents."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import yaml
from scripts.platform import platform_adapter as adapter
from scripts.platform.platform_package import validate, sha
from scripts.upstream.patchsets import patch_hash

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / 'metadata/build/wayland-policy.json'


def policy():
    p = json.loads(POLICY.read_text())
    rows = json.loads((ROOT/'metadata/platform/matrix.json').read_text())['entries']
    p['targets'] = [dict(t, runtime=t['real_remote_session_validation'], status=t['support_status']) for t in rows if t['id'] in p['target_ids']]
    if {t['id'] for t in p['targets']} != set(p['target_ids']) or len(p['targets']) != 2:
        raise ValueError('ARCH: canonical Wayland target set missing/duplicate')
    if any(t['enabled'] or t['required'] or not t['workflow_enabled'] or t['dedicated_workflow']!='wayland.yml' or t['support_status']!='EXPERIMENTAL' for t in p['targets']):
        raise ValueError('PROVENANCE: experimental workflow scope changed')
    return p


def profiles():
    p = policy()
    return [p] + p.get('additional_profiles', [])


def policy_for_pin(pin):
    matches = [p for p in profiles() if p['libdrmtap_sha'] == pin]
    if len(matches) != 1:
        raise ValueError('PROVENANCE: unreviewed or ambiguous libdrmtap pin')
    return matches[0]


def validate_source_policy(info, manifest):
    p = policy_for_pin(info.get('libdrmtap_sha'))
    if manifest.get('files', {}).get('build.py') != p['build_py_sha256']:
        raise ValueError('PROVENANCE: DRM dependency pin does not match exact prepared packaging source')


def policy_for_tree(tree, build=None):
    build = (tree / 'build.py').read_bytes() if build is None else build
    job = yaml.safe_load((tree / '.github/workflows/flutter-build.yml').read_text())['jobs'].get('build-rustdesk-linux-drm')
    if job is None or job.get('if') is False:
        raise ValueError('BUILD_COMPAT: official DRM job missing/disabled')
    candidates = [p for p in profiles() if adapter.digest(job) == p['upstream_drm_job_sha256']]
    if not candidates:
        raise ValueError('BUILD_COMPAT: unreviewed official DRM recipe')
    matches = [p for p in candidates if hashlib.sha256(build).hexdigest() == p['build_py_sha256']]
    if len(matches) != 1:
        raise ValueError('BUILD_COMPAT: unreviewed DRM packaging interface')
    return matches[0]


def policy_for_built_tree(tree, arch):
    tree = Path(tree)
    if arch not in ('x86_64', 'aarch64'):
        raise ValueError('ARCH: unreviewed Wayland packaging architecture')
    manifest = json.loads((tree / 'source-manifest.json').read_text())
    source_sha = manifest.get('upstream_sha', '')
    if not re.fullmatch('[0-9a-f]{40}', source_sha) or source_sha != os.environ.get('UPSTREAM_EXPECTED_SHA'):
        raise ValueError('PROVENANCE: built packaging source SHA mismatch')
    original = subprocess.check_output(['git', '-C', str(tree), 'show', source_sha + ':build.py'])
    if hashlib.sha256(original).hexdigest() != manifest.get('files', {}).get('build.py'):
        raise ValueError('PROVENANCE: original packaging file differs from prepared inventory')
    p = policy_for_tree(tree, original)
    expected = original
    if arch == 'aarch64':
        # Exactly the two substitutions in the reviewed official ARM Linux recipe.
        expected = expected.replace(b'flutter build linux --release', b'flutter-elinux build linux --verbose')
        expected = expected.replace(b'x64/release', b'arm64/release')
    if (tree / 'build.py').read_bytes() != expected:
        raise ValueError('BUILD_COMPAT: unreviewed post-build packaging modification')
    return p


def preflight(tree, arch):
    tree = Path(tree)
    p = policy()
    target = next((t for t in p['targets'] if t['arch'] == arch), None)
    if target is None:
        raise ValueError('ARCH: unreviewed unattended architecture')
    profile, _ = adapter.check(tree, 'linux', arch)
    if profile['runner'] != target['runner']:
        raise ValueError('BUILD_COMPAT: native runner mismatch')
    p = policy_for_tree(tree)
    build = (tree / 'build.py').read_bytes()
    text = build.decode()
    for name, value in [('LIBDRMTAP_REPO_PINNED', p['libdrmtap_repository']),
                        ('LIBDRMTAP_SHA_PINNED', p['libdrmtap_sha'])]:
        if not re.search(r'^' + name + r' = ' + re.escape(repr(value)) + '$', text, re.M):
            raise ValueError('PROVENANCE: libdrmtap source pin drift')
    for name in os.environ:
        if name.startswith('DRMTAP_'):
            raise ValueError('PROVENANCE: DRMTAP environment overrides forbidden')
    return profile


def recipe(tree, arch, out):
    preflight(tree, arch)
    adapter.linux_scripts(tree, arch, out)
    path = out / 'build.sh'
    text = path.read_text()
    compile_line = 'cargo build --locked --lib $JOBS --features hwcodec,flutter,unix-file-copy-paste --release'
    package_line = 'python3 ./build.py --flutter --skip-cargo'
    if text.count(compile_line) != 1 or text.count(package_line) != 1:
        raise ValueError('BUILD_COMPAT: reviewed Linux recipe changed')
    tests = '''
export DRMTAP_PREBUILT_DIR=/workspace/third_party/libdrmtap/build-pkg
FEATURES=$(python3 ./build.py --flutter --drm --hwcodec --unix-file-copy-paste --print-features)
for want in drm drm-wake; do
  case ",$FEATURES," in *",$want,"*) ;; *) echo "BUILD_COMPAT: missing $want"; exit 1;; esac
done
DRM_TEST_TOTAL=0
DRM_TEST_GROUPS=0
run_drm_tests() {
  local out ran
  out=$("$@" 2>&1) || { printf '%s\\n' "$out"; return 1; }
  ran=$(printf '%s\\n' "$out" | awk '/^running [0-9]+ tests?$/ { n += $2 } END { print n+0 }')
  printf 'DRM tests: %s executed\\n' "$ran"
  test "$ran" -gt 0
  DRM_TEST_TOTAL=$((DRM_TEST_TOTAL + ran))
  DRM_TEST_GROUPS=$((DRM_TEST_GROUPS + 1))
}
'''
    for package, filters in [('', ['drm_capturer_tests', 'ipc::test', 'cursor_pos_tests', 'peer_abs_sample_tests', 'input_map_tests']),
                             ('-p scrap ', ['hotspot_provenance_tests', 'hotspot_guess_tests', 'plane_rotation_tests'])]:
        for test in filters:
            tests += f'run_drm_tests cargo test --locked {package}--lib --features drm {test}\n'
    if policy_for_tree(tree)['drm_test_groups'] == 12:
        tests += 'run_drm_tests cargo test --locked --lib --features drm drm_pacing_tests\n'
        tests += 'run_drm_tests cargo test --locked -p scrap --lib --features drm crtc_refresh_tests\n'
        tests += 'run_drm_tests cargo test --locked -p scrap --lib --features drm drmtap_dl::tests\n'
        tests += 'run_drm_tests cargo test --locked -p clipboard --features unix-file-copy-paste\n'
    tests += '''printf '{"groups":%s,"tests":%s}\\n' "$DRM_TEST_GROUPS" "$DRM_TEST_TOTAL" > /workspace/wayland-tests.json
'''
    tests += 'cargo build --locked --lib $JOBS --features "$FEATURES" --release'
    text = text.replace(compile_line, tests).replace(package_line,
        'python3 ./build.py --flutter --drm --hwcodec --unix-file-copy-paste --skip-cargo')
    # RPM is not DRM-aware upstream; never emit a stock-named RPM from this lane.
    if text.count('# rpm package') != 1:
        raise ValueError('BUILD_COMPAT: RPM boundary changed')
    text = text.split('# rpm package', 1)[0]
    path.write_text(text)
    return sha(POLICY)


def aggregate(root, output):
    expected = {t['arch'] for t in policy()['targets']}
    found = {}
    identities = []
    for f in Path(root).rglob('build-info.json'):
        info = validate(f.parent)
        if info.get('build_flavor') != 'unattended-wayland' or info['platform'] != 'linux' or info['variant'] != 'standard':
            raise ValueError('PROVENANCE: unexpected flavor/source variant')
        arch = info['architecture']
        if arch not in expected or arch in found:
            raise ValueError('ARCH: duplicate/unexpected target')
        for key, env in [('upstream_sha', 'UPSTREAM_EXPECTED_SHA'), ('upstream_version', 'UPSTREAM_VERSION'),
                         ('custom_repository_sha', 'GITHUB_SHA'), ('build_run', 'GITHUB_RUN_ID'), ('patchset', 'PATCHSET')]:
            if not os.environ.get(env) or str(info[key]) != os.environ[env]:
                raise ValueError('PROVENANCE: exact aggregate identity required: ' + key)
        if info['channel'] != os.environ.get('BUILD_CHANNEL', 'stable') or info.get('wayland_policy_sha256') != sha(POLICY):
            raise ValueError('PROVENANCE: channel/policy mismatch')
        identities.append(tuple(str(info[k]) for k in ['upstream_sha', 'custom_repository_sha', 'build_run', 'common_patch_hash']))
        found[arch] = {'packages': {p.name: sha(p) for p in (f.parent / 'packages').iterdir()},
                       'build_info_sha256': sha(f), 'runtime_validation': 'NOT TESTED'}
    if set(found) != expected or len(set(identities)) != 1:
        raise ValueError('PROVENANCE: both architectures from the same batch are required')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'schema': 'wayland-qualification-v1', 'result': 'PASS',
        'scope': 'EXPERIMENTAL BUILD AND PACKAGE ONLY', 'publication_authorized': False,
        'channel': os.environ.get('BUILD_CHANNEL', 'stable'),
        'custom_sha': os.environ['GITHUB_SHA'], 'upstream_sha': os.environ['UPSTREAM_EXPECTED_SHA'],
        'upstream_version': os.environ['UPSTREAM_VERSION'], 'patchset': os.environ['PATCHSET'],
        'common_patch_hash': patch_hash('common', os.environ['PATCHSET']),
        'workflow_run': os.environ['GITHUB_RUN_ID'], 'policy_sha256': sha(POLICY), 'targets': found}, indent=2) + '\n')


def attach_assets(root, directory, peer, channel):
    if channel not in policy()['channels'] or channel != os.environ.get('BUILD_CHANNEL'):
        raise ValueError('PROVENANCE: Wayland parent channel mismatch')
    report = ROOT / '.work/wayland-qualification.json'
    aggregate(root, report)
    for f in Path(root).rglob('build-info.json'):
        info = validate(f.parent)
        for key in ['prepared_source_identity', 'prepare_run', 'common_patch_hash', 'server_config_fingerprint']:
            if info.get(key) is None or str(info[key]) != str(peer.get(key)):
                raise ValueError('PROVENANCE: Wayland/ordinary source or configuration mismatch: ' + key)
        for package in (f.parent / 'packages').iterdir():
            if (directory / package.name).exists():
                raise ValueError('PACKAGE: Wayland asset collision')
            shutil.copy2(package, directory / package.name)
    return json.loads(report.read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    for name in ['preflight', 'recipe']:
        p = sub.add_parser(name)
        p.add_argument('--tree', type=Path, required=True)
        p.add_argument('--arch', required=True)
        if name == 'recipe':
            p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('aggregate')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'aggregate':
        aggregate(args.root, args.output)
    elif args.mode == 'recipe':
        recipe(args.tree, args.arch, args.out)
    else:
        preflight(args.tree, args.arch)
    print('Wayland ' + args.mode + ': PASS')
