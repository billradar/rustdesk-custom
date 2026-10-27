#!/usr/bin/env python3
"""Reviewed DRM recipes and same-run four-target qualification for Tag/Nightly parents."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import yaml
from scripts.platform import platform_adapter as adapter
from scripts.platform.platform_package import validate, sha
from scripts.upstream.patchsets import patch_hash

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / 'metadata/build/wayland-policy.json'


def policy():
    p = json.loads(POLICY.read_text())
    if (p.get('schema') != 'wayland-build-policy-v2' or p.get('build_flavor') != 'unattended-wayland'
            or p.get('package_name') != 'rustdesk-unattended-wayland'
            or p.get('asset_naming') != 'rustdesk-unattended-wayland-{variant}-{version}-{arch}.deb'):
        raise ValueError('PACKAGE: unreviewed Wayland package identity')
    rows = json.loads((ROOT/'metadata/platform/matrix.json').read_text())['entries']
    p['targets'] = [dict(t, runtime=t['real_remote_session_validation'], status=t['support_status']) for t in rows if t['id'] in p['target_ids']]
    expected = {(v, a) for v in ('standard', 'sos') for a in ('x86_64', 'aarch64')}
    actual = {(t['source_variant'], t['arch']) for t in p['targets']}
    if (p.get('source_variants') != ['standard', 'sos'] or actual != expected
            or {t['id'] for t in p['targets']} != set(p['target_ids']) or len(p['target_ids']) != 4 or len(p['targets']) != 4):
        raise ValueError('ARCH: canonical Wayland target set missing/duplicate')
    if any(t['enabled'] or t['required'] or not t['workflow_enabled'] or t['dedicated_workflow']!='wayland.yml' or t['support_status']!='EXPERIMENTAL' for t in p['targets']):
        raise ValueError('PROVENANCE: experimental workflow scope changed')
    return p


def package_name(version, variant, arch):
    if (variant not in ('standard', 'sos') or arch not in ('x86_64', 'aarch64')
            or not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)):
        raise ValueError('PACKAGE: invalid Wayland asset identity')
    return policy()['asset_naming'].format(variant=variant, version=version, arch=arch)


def asset_names(version):
    return {package_name(version, t['source_variant'], t['arch']) for t in policy()['targets']}


def label_package(package, variant):
    """Label the DEB without changing its package identity, scripts or payload."""
    if variant not in ('standard', 'sos'):
        raise ValueError('PACKAGE: unreviewed source variant')
    package = Path(package).resolve()
    name = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Package'], text=True).strip()
    if name != policy()['package_name']:
        raise ValueError('PACKAGE: cannot label a stock package as unattended')
    with tempfile.TemporaryDirectory(prefix='rustdesk-wayland-label-') as temp:
        stage = Path(temp) / 'package'
        subprocess.run(['dpkg-deb', '--raw-extract', str(package), str(stage)], check=True)
        control = stage / 'DEBIAN/control'
        text, count = re.subn(r'^Description:[^\n]*',
                             'Description: RustDesk Wayland unattended (' + variant.upper() + ')',
                             control.read_text(), flags=re.M)
        if count != 1:
            raise ValueError('PACKAGE: missing/duplicate description')
        control.write_text(text)
        labeled = Path(temp) / 'labeled.deb'
        subprocess.run(['dpkg-deb', '-Zxz', '--build', '--root-owner-group', str(stage), str(labeled)],
                       check=True, stdout=subprocess.DEVNULL)
        # Temporary files can live on another filesystem from the build tree.
        shutil.copy2(labeled, package)


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


def preflight(tree, arch, variant='standard'):
    tree = Path(tree)
    p = policy()
    target = next((t for t in p['targets'] if t['arch'] == arch and t['source_variant'] == variant), None)
    if target is None:
        raise ValueError('ARCH: unreviewed unattended architecture')
    manifest = tree / 'source-manifest.json'
    if variant == 'sos' and not manifest.is_file():
        raise ValueError('PROVENANCE: prepared SOS source manifest required')
    if manifest.exists() and json.loads(manifest.read_text()).get('variant') != variant:
        raise ValueError('PROVENANCE: prepared source variant mismatch')
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


def recipe(tree, arch, out, variant='standard'):
    preflight(tree, arch, variant)
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
    expected = {(t['source_variant'], t['arch']) for t in policy()['targets']}
    found = {}
    identities = []
    sources = {}
    for f in Path(root).rglob('build-info.json'):
        info = validate(f.parent)
        variant, arch = info['variant'], info['architecture']
        if info.get('build_flavor') != 'unattended-wayland' or info['platform'] != 'linux':
            raise ValueError('PROVENANCE: unexpected flavor/source variant')
        key = (variant, arch)
        target = variant + '-' + arch
        if key not in expected or target in found:
            raise ValueError('ARCH: duplicate/unexpected target')
        for field, env in [('upstream_sha', 'UPSTREAM_EXPECTED_SHA'), ('upstream_version', 'UPSTREAM_VERSION'),
                           ('custom_repository_sha', 'GITHUB_SHA'), ('build_run', 'GITHUB_RUN_ID'), ('patchset', 'PATCHSET')]:
            if not os.environ.get(env) or str(info[field]) != os.environ[env]:
                raise ValueError('PROVENANCE: exact aggregate identity required: ' + field)
        if info['channel'] != os.environ.get('BUILD_CHANNEL', 'stable') or info.get('wayland_policy_sha256') != sha(POLICY):
            raise ValueError('PROVENANCE: channel/policy mismatch')
        common = patch_hash('common', info['patchset'])
        sos = patch_hash('sos', info['patchset']) if variant == 'sos' else None
        if info.get('common_patch_hash') != common or info.get('sos_patch_hash') != sos:
            raise ValueError('PROVENANCE: variant patch hash mismatch')
        source = tuple(info.get(k) for k in ['prepared_source_identity', 'prepare_run', 'server_config_fingerprint'])
        if any(x is None for x in source) or (variant in sources and sources[variant] != source):
            raise ValueError('PROVENANCE: same-variant prepared source mismatch')
        sources[variant] = source
        identities.append(tuple(str(info[k]) for k in ['upstream_sha', 'custom_repository_sha', 'build_run',
                                                       'common_patch_hash', 'libdrmtap_sha', 'server_config_fingerprint']))
        packages = list((f.parent / 'packages').iterdir())
        if len(packages) != 1 or packages[0].name != package_name(info['upstream_version'], variant, arch):
            raise ValueError('PACKAGE: exact Wayland asset name required')
        found[target] = {'variant': variant, 'architecture': arch,
                         'packages': {p.name: sha(p) for p in packages},
                         'sos_patch_hash': sos, 'prepared_source_identity': source[0],
                         'build_info_sha256': sha(f), 'runtime_validation': 'NOT TESTED'}
    if set(found) != {v + '-' + a for v, a in expected} or len(set(identities)) != 1:
        raise ValueError('PROVENANCE: all four targets from the same batch are required')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'schema': 'wayland-qualification-v2', 'result': 'PASS',
        'scope': 'EXPERIMENTAL BUILD AND PACKAGE ONLY', 'publication_authorized': False,
        'channel': os.environ.get('BUILD_CHANNEL', 'stable'),
        'custom_sha': os.environ['GITHUB_SHA'], 'upstream_sha': os.environ['UPSTREAM_EXPECTED_SHA'],
        'upstream_version': os.environ['UPSTREAM_VERSION'], 'patchset': os.environ['PATCHSET'],
        'common_patch_hash': patch_hash('common', os.environ['PATCHSET']),
        'sos_patch_hash': patch_hash('sos', os.environ['PATCHSET']),
        'workflow_run': os.environ['GITHUB_RUN_ID'], 'policy_sha256': sha(POLICY), 'targets': found}, indent=2) + '\n')


def attach_assets(root, directory, peers, channel):
    if channel not in policy()['channels'] or channel != os.environ.get('BUILD_CHANNEL'):
        raise ValueError('PROVENANCE: Wayland parent channel mismatch')
    report = ROOT / '.work/wayland-qualification.json'
    aggregate(root, report)
    copies = []
    for f in Path(root).rglob('build-info.json'):
        info = validate(f.parent)
        peer = peers.get((info['variant'], info['architecture']))
        if peer is None or peer.get('platform') != 'linux':
            raise ValueError('PROVENANCE: matching ordinary Linux peer missing')
        for key in ['variant', 'architecture', 'prepared_source_identity', 'prepare_run',
                    'common_patch_hash', 'sos_patch_hash', 'server_config_fingerprint',
                    'upstream_sha', 'upstream_version', 'patchset', 'custom_repository_sha', 'build_run', 'channel']:
            if key not in info or key not in peer or info[key] != peer[key]:
                raise ValueError('PROVENANCE: Wayland/ordinary source or configuration mismatch: ' + key)
        for package in (f.parent / 'packages').iterdir():
            if (directory / package.name).exists():
                raise ValueError('PACKAGE: Wayland asset collision')
            copies.append(package)
    # Validate the entire set before copying any assets into the release directory.
    for package in copies:
        shutil.copy2(package, directory / package.name)
    return json.loads(report.read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    for name in ['preflight', 'recipe']:
        p = sub.add_parser(name)
        p.add_argument('--tree', type=Path, required=True)
        p.add_argument('--arch', required=True)
        p.add_argument('--variant', choices=['standard', 'sos'], default='standard')
        if name == 'recipe':
            p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('aggregate')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'aggregate':
        aggregate(args.root, args.output)
    elif args.mode == 'recipe':
        recipe(args.tree, args.arch, args.out, args.variant)
    else:
        preflight(args.tree, args.arch, args.variant)
    print('Wayland ' + args.mode + ': PASS')
