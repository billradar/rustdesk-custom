#!/usr/bin/env python3
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.release.naming import windows_installer_name

EXPECTED_SHA = os.environ.get('UPSTREAM_EXPECTED_SHA')
BRIDGE_FILES = [
    'src/bridge_generated.rs', 'src/bridge_generated.io.rs',
    'flutter/lib/generated_bridge.dart', 'flutter/lib/generated_bridge.freezed.dart',
    'flutter/macos/Runner/bridge_generated.h', 'flutter/ios/Runner/bridge_generated.h',
]

def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()

def patch_hash(root, folder):
    from scripts.upstream.patchsets import patch_hash as digest
    return digest(folder)


def build_windows_installers(tree, release, packages, version):
    """Build the same user-facing Windows EXE/MSI installers used by upstream."""
    packages.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault('PYTHONUNBUFFERED', '1')

    # Upstream's self-extracted installer is generated from the complete Release
    # directory. Keep the internal unpacked bundle for audit, but publish only the
    # generated installer executable.
    manifest = tree / 'res/manifest.xml'
    if manifest.is_file():
        subprocess.run(['sed', '-i', '/dpiAware/d', str(manifest)], cwd=tree, check=True, env=env)
    portable = (
        'pushd libs/portable && '
        'pip3 install -r requirements.txt && '
        'python3 ./generate.py -f ../../flutter/build/windows/x64/runner/Release '
        '-o . -e ../../flutter/build/windows/x64/runner/Release/rustdesk.exe && '
        'popd'
    )
    subprocess.run(['bash', '-lc', portable], cwd=tree, check=True, env=env)
    packed = tree / 'target/release/rustdesk-portable-packer.exe'
    if not packed.is_file() or packed.stat().st_size == 0:
        raise ValueError('Windows self-extracted EXE was not generated')
    exe = packages / windows_installer_name(version, os.environ.get('BUILD_VARIANT', 'standard'), 'exe')
    shutil.copy2(packed, exe)

    # Upstream builds the MSI from res/msi using the reviewed WiX project.
    # setup-msbuild is installed by the calling workflow before this script runs.
    msi_script = (
        'cd res/msi && '
        'python preprocess.py --arp -d ../../flutter/build/windows/x64/runner/Release && '
        'nuget restore msi.sln && '
        'msbuild msi.sln -p:Configuration=Release -p:Platform=x64 /p:TargetVersion=Windows10'
    )
    subprocess.run(['bash', '-lc', msi_script], cwd=tree, check=True, env=env)
    candidates = sorted((tree / 'res/msi/Package/bin').glob('*/Release/en-us/Package.msi'))
    if not candidates:
        raise ValueError('Windows MSI was not generated')
    msi = candidates[0]
    if msi.stat().st_size == 0:
        raise ValueError('Generated Windows MSI is empty')
    msi_out = packages / windows_installer_name(version, os.environ.get('BUILD_VARIANT', 'standard'), 'msi')
    shutil.copy2(msi, msi_out)
    return exe, msi_out

command, tree, *args = sys.argv[1:]
tree = Path(tree)
if command == 'restore-bridge':
    bridge = Path(args[0])
    info = json.loads((bridge / 'bridge-info.json').read_text())
    if info['upstream_sha'] != git(tree, 'rev-parse', 'HEAD') or (EXPECTED_SHA and info['upstream_sha'] != EXPECTED_SHA):
        raise SystemExit('Bridge/source upstream SHA mismatch')
    for name in BRIDGE_FILES:
        src = bridge / name
        if hashlib.sha256(src.read_bytes()).hexdigest() != info['files'][name]:
            raise SystemExit(f'Bridge hash mismatch: {name}')
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, tree / name)
elif command == 'bridge-info':
    info = {'upstream_sha': git(tree, 'rev-parse', 'HEAD'), 'files': {}}
    if EXPECTED_SHA and info['upstream_sha'] != EXPECTED_SHA:
        raise SystemExit('Unsupported bridge upstream SHA')
    for name in BRIDGE_FILES:
        info['files'][name] = hashlib.sha256((tree / name).read_bytes()).hexdigest()
    (tree / 'bridge-info.json').write_text(json.dumps(info, indent=2) + '\n')
elif command == 'package':
    variant, ref, output, root = args
    if variant not in ('standard', 'sos'):
        raise SystemExit('Invalid variant')
    output, root = Path(output), Path(root)
    release = tree / 'flutter/build/windows/x64/runner/Release'
    for name in ['rustdesk.exe', 'librustdesk.dll', 'flutter_windows.dll', 'dylib_virtual_display.dll']:
        if not (release / name).is_file() or (release / name).stat().st_size == 0:
            raise SystemExit(f'Missing compiled output: {name}')
    if not (release / 'data/flutter_assets').is_dir():
        raise SystemExit('Missing Flutter assets')
    library = (release / 'librustdesk.dll').read_bytes()
    # Test binaries must carry the compile-time inputs, rather than merely having env vars.
    # Never print the values, password digest, or any part of the executable.
    for name in ['RUSTDESK_ID_SERVER', 'RUSTDESK_API_SERVER', 'RUSTDESK_KEY']:
        value = os.environ.get(name, '').encode()
        if not value or value not in library:
            raise SystemExit(f'Compiled configuration not found: {name} (value withheld)')
    relay = os.environ.get('RUSTDESK_RELAY_SERVER', '').encode()
    if relay and relay not in library:
        raise SystemExit('Compiled relay configuration not found (value withheld)')
    # Do not assume optimized short strings survive as contiguous DLL bytes.
    # Query the built DLL's existing configuration API instead.
    native_library = tree / 'target/release/librustdesk.dll'
    if not native_library.is_file() or native_library.read_bytes() != library:
        raise SystemExit('Packaged DLL differs from the freshly built Rust DLL')
    configuration = os.environ.get('BUILD_CONFIGURATION', 'TEST ONLY')
    if configuration == 'PRODUCTION':
        from scripts.signing.production_config import compiled
        compiled(release / 'librustdesk.dll')
    else:
        from scripts.validation.native_config_probe import verify
        verify(release / 'librustdesk.dll')
    print('Compiled configuration presence: PASS (values withheld)')
    topmost = Path(os.environ['RUSTDESK_TOPMOST_DLL'])
    if not topmost.is_file():
        raise SystemExit('Missing WindowInjection.dll')
    shutil.copy2(topmost, release / 'WindowInjection.dll')
    version = (os.environ.get('ARTIFACT_IDENTITY') or os.environ.get('UPSTREAM_TAG') or 'source-' + git(tree, 'rev-parse', 'HEAD')[:12]).lstrip('v')
    import re
    if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z.-]{0,80}', version):
        raise SystemExit('Invalid artifact version')
    suffix = '' if configuration == 'PRODUCTION' else '-test'
    os.environ['BUILD_VARIANT'] = variant
    folder = output / f'rustdesk-{version}-{variant}{suffix}-windows-x86_64'
    if folder.exists():
        raise SystemExit('Artifact destination already exists; never overwrite it')
    sha = git(tree, 'rev-parse', 'HEAD')
    if EXPECTED_SHA and sha != EXPECTED_SHA:
        raise SystemExit('Unexpected artifact upstream SHA')
    folder.mkdir(parents=True)
    shutil.copytree(release, folder / 'rustdesk')
    build_windows_installers(tree, release, folder / 'packages', version)
    # Keep the unpacked bundle and provenance internally; Release/Draft publication
    # selects only the generated Windows installers from packages/.
    info = {
        'variant': variant,
        'patchset': os.environ.get('PATCHSET', 'v1'),
        'upstream_repository': 'rustdesk/rustdesk',
        'upstream_ref': ref,
        'upstream_sha': sha,
        'upstream_tag': os.environ.get('UPSTREAM_TAG'),
        'patch_revision': os.environ.get('PATCH_REVISION', '1'),
        'upstream_version': os.environ.get('UPSTREAM_VERSION', version),
        'channel': os.environ.get('BUILD_CHANNEL', 'stable'),
        'hbb_common_sha': git(tree / 'libs/hbb_common', 'rev-parse', 'HEAD'),
        'custom_repository': os.environ.get('GITHUB_REPOSITORY', 'billradar/rustdesk-custom'),
        'architecture': 'x86_64',
        'configuration_validation': 'PASS',
        'password_configuration_validation': 'PASS',
        'password_validation_method': 'built-dll-native-bridge',
        'custom_repository_sha': git(root, 'rev-parse', 'HEAD'),
        'common_patch_hash': patch_hash(root, 'common'),
        'sos_patch_hash': patch_hash(root, 'sos') if variant == 'sos' else None,
        'build_time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'workflow_run': os.environ.get('GITHUB_RUN_ID'),
        'platform': 'windows-x86_64',
        'signed': False,
        'configuration': configuration,
        'runtime_ui_validation': 'SKIPPED BY USER',
        'real_remote_session_validation': 'NOT TESTED',
    }
    if (tree / 'source-manifest.json').exists():
        manifest = json.loads((tree / 'source-manifest.json').read_text())
        info.update(prepare_run=manifest['prepare_workflow_run'], build_run=os.environ.get('GITHUB_RUN_ID'),
                    prepared_source_manifest_hash=hashlib.sha256((tree / 'source-manifest.json').read_bytes()).hexdigest(),
                    build_adapter_signature=manifest['build_adapter_signature'])
        from scripts.build.build_adapter import check
        profile = check(tree)
        engine = os.environ.get('ENGINE_ARCHIVE_SHA256', '')
        if not re.fullmatch('[0-9a-f]{64}', engine):
            raise SystemExit('Official engine download identity missing')
        info['engine_archive_sha256'] = engine
        info['build_toolchain'] = {k: profile[k] for k in ('rust', 'flutter', 'llvm', 'vcpkg', 'helper_commit', 'bridge_rust', 'bridge_flutter', 'frb', 'cargo_expand')}
        shutil.copy2(tree / 'source-manifest.json', folder / 'source-manifest.json')
    if configuration == 'PRODUCTION':
        from scripts.signing.production_config import server_fingerprint
        info['server_config_fingerprint'] = server_fingerprint()
    info.update(prepared_source_identity=info.get('prepared_source_manifest_hash'),
                platform_patch_hash=None, runner=os.environ.get('RUNNER_OS'),
                runner_arch=os.environ.get('RUNNER_ARCH'), runner_image=os.environ.get('ImageOS'),
                build_job=os.environ.get('GITHUB_JOB'), package_type='portable-flutter-bundle',
                signed_status='NOT ENABLED')
    (folder / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
    shutil.copy2(root / 'patchsets' / os.environ.get('PATCHSET', 'v1') / 'patchset.json', folder / 'patchset.json')
    # Preserve corresponding patch source and the AGPL licence with the test bundle.
    if (tree / 'custom-source.sbom.json').exists():
        shutil.copy2(tree / 'custom-source.sbom.json', folder / 'custom-source.sbom.json')
    shutil.copy2(tree / 'LICENCE', folder / 'LICENCE')
    shutil.copy2(root / 'README.md', folder / 'SOURCE-README.md')
    shutil.copytree(root / 'patchsets' / os.environ.get('PATCHSET', 'v1') / 'common', folder / 'patches/common')
    if variant == 'sos':
        shutil.copytree(root / 'patchsets' / os.environ.get('PATCHSET', 'v1') / 'sos', folder / 'patches/sos')
    entries = []
    for file in sorted(folder.rglob('*')):
        if file.is_file():
            entries.append(hashlib.sha256(file.read_bytes()).hexdigest() + '  ' + file.relative_to(folder).as_posix())
    (folder / 'SHA256SUMS').write_text('\n'.join(entries) + '\n')
    subprocess.run([sys.executable, str(root / 'scripts/release/github.py'), 'validate', str(folder)], check=True)
    print(f'Test artifact ready: {folder.name}')
else:
    raise SystemExit('Unknown command')
