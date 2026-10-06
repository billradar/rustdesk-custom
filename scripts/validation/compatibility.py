#!/usr/bin/env python3
"""Strict patch/API checks. Reports failures; never edits tracked patches or publishes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FILES = ['src/common.rs', 'src/flutter.rs', 'src/flutter_ffi.rs', 'libs/hbb_common/src/config.rs'] + [
    'flutter/lib/desktop/pages/' + f + '.dart' for f in
    ('connection_page', 'desktop_home_page', 'desktop_setting_page', 'desktop_tab_page')]

def run(command, log):
    with log.open('a') as stream:
        stream.write('\n$ ' + ' '.join(map(str, command)) + '\n')
        stream.flush()
        completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
    if completed.returncode:
        # Diagnostic source/patch/compiler logs contain only fictional test configuration.
        print(log.read_text()[-18000:])
        raise RuntimeError(f'Command failed ({completed.returncode}); see {log}')

def contracts(tree, variant, patchset=None):
    patchset=patchset or os.environ.get("PATCHSET", "v1")
    texts = {}
    for file in FILES:
        path = tree / file
        if not path.is_file():
            raise RuntimeError('Missing dependency file: ' + file)
        texts[file] = path.read_text()
    hbb = texts['libs/hbb_common/src/config.rs']
    for token in ('HARD_SETTINGS', 'DEFAULT_SETTINGS', 'BUILTIN_SETTINGS',
                  'pub fn get_option(',
                  'pub fn get_rendezvous_server(', 'pub fn is_incoming_only(', 'pub fn is_disable_settings('):
        if token not in hbb:
            raise RuntimeError('Missing hbb configuration API: ' + token)
    key_source = hbb if patchset == 'v1' else (tree / 'libs/base/src/config/keys.rs').read_text()
    if 'OPTION_ALLOW_REMOTE_CONFIG_MODIFICATION' not in key_source:
        raise RuntimeError('Missing generation configuration API: OPTION_ALLOW_REMOTE_CONFIG_MODIFICATION')
    common = texts['src/common.rs']
    expected_key = ('config::keys::' if patchset == 'v1' else 'base::config::keys::') + 'OPTION_ALLOW_REMOTE_CONFIG_MODIFICATION'
    if expected_key not in common:
        raise RuntimeError('Wrong generation config-key API wiring')
    for token in ('pub fn load_custom_client()', 'fn get_api_server_(',
                  'pub fn get_custom_rendezvous_server(', 'use-permanent-password',
                  'verification-method', 'allow-hide-cm', 'relay-server'):
        if token not in common:
            raise RuntimeError('Missing Common API/config dependency: ' + token)
    flutter = texts['src/flutter_ffi.rs'] + texts['src/flutter.rs']
    for token in ('fn main_get_buildin_option(', 'fn is_incoming_only(', 'fn is_disable_settings(', 'fn session_add('):
        if token not in flutter:
            raise RuntimeError('Missing native Flutter bridge API: ' + token)
    home = texts['flutter/lib/desktop/pages/desktop_home_page.dart']
    settings = texts['flutter/lib/desktop/pages/desktop_setting_page.dart']
    tab = texts['flutter/lib/desktop/pages/desktop_tab_page.dart']
    connection = texts['flutter/lib/desktop/pages/connection_page.dart']
    for label, text, tokens in [
        ('Home', home, ('buildIDBoard(', 'gFFI.serverModel', 'buildLeftPane(', 'buildRightPane(')),
        ('Settings', settings, ('class DesktopSettingPage', 'SettingsTabKey.about', 'hide_cm(!locked)')),
        ('Connection', connection, ('startServiceWidget()', 'setupServerWidget()')),
        ('Tab', tab, ('class DesktopTabPage', 'DesktopTab(', 'ActionIcon(')),
    ]:
        for token in tokens:
            if token not in text:
                raise RuntimeError(f'Missing Flutter {label} API: {token}')
    if variant == 'sos':
        for label, text, tokens in [
            ('Home', home, ('final isSosMode', '!isIncomingOnly && !isSosMode', 'isSosMode ? const Offstage()', 'if (isIncomingOnly || isSosMode)')),
            ('Settings', settings, ("bind.mainGetBuildinOption(key: 'sos-mode') != 'Y'",)),
            ('Tab', tab, ("bind.isDisableSettings() || bind.mainGetBuildinOption(key: 'sos-mode') == 'Y'",)),
            ('Connection', connection, ("!isIncomingOnly && bind.mainGetBuildinOption(key: 'sos-mode') != 'Y'",)),
        ]:
            for token in tokens:
                if token not in text:
                    raise RuntimeError(f'SOS restriction changed: {label}: {token}')
        keys = settings[settings.index('static final List<SettingsTabKey> tabKeys'):settings.index('SettingsTabKey.about')]
        if keys.count("mainGetBuildinOption(key: 'sos-mode')") != (7 if patchset == 'v1' else 6):
            raise RuntimeError('SOS settings guard coverage changed')
    elif 'final isSosMode' in home or '"sos-mode"' in common:
        raise RuntimeError('SOS customization leaked into Standard')
    return {'Config API': 'PASS', 'Rust API structure': 'PASS', 'Flutter API structure': 'PASS',
            'SOS UI structure': 'PASS' if variant == 'sos' else 'N/A'}

def build_system(tree):
    baseline = json.loads((ROOT / 'metadata/baselines/build.json').read_text())
    changed = []
    for file, digest in baseline.items():
        path = tree / file
        if not path.is_file() or hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != digest:
            changed.append(file)
    for path in (tree / '.github/workflows').rglob('*'):
        if path.is_file() and path.relative_to(tree).as_posix() not in baseline:
            changed.append(path.relative_to(tree).as_posix())
    for file in ('build.py', 'Cargo.toml', 'Cargo.lock', 'flutter/pubspec.yaml', '.gitmodules', 'vcpkg.json',
                 '.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff'):
        if not (tree / file).is_file():
            raise RuntimeError('Windows build adapter dependency missing: ' + file)
    build = (tree / 'build.py').read_text()
    for flag in ('--portable', '--flutter', '--skip-portable-pack', '--hwcodec', '--vram'):
        if flag not in build:
            raise RuntimeError('Windows build interface removed: ' + flag)
    # Explicitly reject a toolchain migration that the historical Windows adapter cannot support.
    cargo = (tree / 'Cargo.toml').read_text()
    if not re.search(r'rust-version\s*=\s*"1\.75(?:\.0)?"', cargo):
        raise RuntimeError('Rust minimum version changed: review pinned Windows adapter')
    return changed

def rust_probe(tree):
    common = (tree / 'src/common.rs').read_text()
    helper = common[common.index('fn apply_custom_build_defaults()'):common.index('\npub fn load_custom_client()')]
    crate = 'hbb_common' if os.environ.get('PATCHSET', 'v1') == 'v1' else 'base'
    manifest = tree / ('libs/' + crate + '/Cargo.toml')
    manifest.write_text(manifest.read_text() + '\n[[bin]]\nname = \"custom_patch_config\"\npath = \"custom_patch_config.rs\"\n')
    path = tree / ('libs/' + crate + '/custom_patch_config.rs')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('use hbb_common::config;\n' + helper + '\nfn main() {\n'
                    'apply_custom_build_defaults();\n'
                    'let _: fn(&str) -> String = config::Config::get_option;\n'
                    'let _: fn() -> String = config::Config::get_rendezvous_server;\n}\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'rust', 'analyze', 'contracts'])
    parser.add_argument('--sha', default=os.environ.get('UPSTREAM_EXPECTED_SHA', ''))
    parser.add_argument('--variant', choices=['standard', 'sos', 'both'], default='both')
    parser.add_argument('--simulate-failure', action='store_true')
    parser.add_argument('--root', default='.work/validation')
    args = parser.parse_args()
    destination = ROOT / args.root
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / 'report.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {
        'patchset': os.environ.get('PATCHSET', 'v1'), 'upstream_repository': 'rustdesk/rustdesk', 'upstream_sha': args.sha,
        'upstream_branch': os.environ.get('UPSTREAM_BRANCH'), 'variants': {},
        'Runtime/UI Validation': 'SKIPPED BY USER', 'Real Remote Session Validation': 'NOT TESTED'}
    variants = ['standard', 'sos'] if args.variant == 'both' else [args.variant]
    try:
        for variant in variants:
            tree = destination / variant
            status = report['variants'].setdefault(variant, {})
            log = destination / (variant + '.log')
            if args.mode == 'prepare':
                if not re.fullmatch('[0-9a-f]{40}', args.sha):
                    raise RuntimeError('Preflight requires frozen 40-character SHA')
                run(['bash', str(ROOT / 'scripts/source/prepare.sh'), args.sha, str(tree)], log)
                if args.simulate_failure:
                    # A synthetic nonexistent target, piped to git; tracked patches stay unchanged.
                    bad = 'diff --git a/nonexistent-simulation b/nonexistent-simulation\n--- a/nonexistent-simulation\n+++ b/nonexistent-simulation\n@@ -1 +1 @@\n-old\n+new\n'
                    result = subprocess.run(['git', '-C', str(tree), 'apply', '--check', '-'], input=bad, text=True, capture_output=True)
                    log.write_text(log.read_text() + result.stderr)
                    if result.returncode == 0:
                        raise RuntimeError('Failure simulation unexpectedly applied')
                    status['Patch Apply'] = 'FAIL (SIMULATED)'
                    raise RuntimeError('Simulated patch conflict: nonexistent-simulation; expensive builds blocked')
                run(['bash', str(ROOT / 'scripts/source/apply_patches.sh'), str(tree), variant], log)
                status['Patch Apply'] = 'PASS'
                status['hbb_common Patch'] = 'PASS'
                run([sys.executable, str(ROOT / 'scripts/source/verify_source.py'), str(tree), variant, '--automation'], log)
                status['Native helper mock compilation/assertions'] = 'PASS'
                status.update(contracts(tree, variant))
                changed = build_system(tree)
                status['Build System'] = 'WARNING' if changed else 'PASS'
                status['Changed build files'] = changed
                status['Rust real-config compile'] = 'NOT RUN'
                status['Flutter Analyze'] = 'NOT RUN'
                rust_probe(tree)
            elif args.mode == 'rust':
                run(['cargo', 'check', '--locked', '--manifest-path', str(tree / 'Cargo.toml'), '-p', ('hbb_common' if os.environ.get('PATCHSET', 'v1') == 'v1' else 'base'), '--bin', 'custom_patch_config'], log)
                status['Rust real-config compile'] = 'PASS'
            elif args.mode == 'analyze':
                with log.open('a') as stream:
                    result = subprocess.run(['flutter', 'pub', 'get'], cwd=tree / 'flutter', stdout=stream, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise RuntimeError(f'Flutter pub get failed: {log}')
                # Only error severity fails. Upstream lint warnings remain in logs.
                with log.open('a') as stream:
                    result = subprocess.run(['flutter', 'analyze', '--no-fatal-infos', '--no-fatal-warnings',
                        *[file.removeprefix('flutter/') for file in FILES if file.endswith('.dart')]],
                        cwd=tree / 'flutter', stdout=stream, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise RuntimeError(f'Flutter analyze errors: {log}')
                status['Flutter Analyze'] = 'PASS'
            else:
                status.update(contracts(tree, variant))
        report['Overall'] = 'PASS'
        if args.mode == 'prepare':
            report['Coverage'] = 'Patch, structural API, native mock compile; real-config Rust and Flutter analyze pending'
    except Exception as error:
        report['Overall'] = 'FAIL'
        report['Reason'] = str(error)
        report['Failed stage'] = args.mode
        report['Failed variant'] = variant if 'variant' in locals() else 'unknown'
        if 'log' in locals() and log.exists():
            diagnostic = log.read_text()
            failed_patch = re.search(r'STOP: failed patch ([^;]+)', diagnostic)
            if failed_patch:
                report['Failed patch'] = failed_patch.group(1)
            report['Failed files'] = sorted(set(re.findall(r'error: patch failed: (.+?):[0-9]+', diagnostic)))
        print(str(error), file=sys.stderr)
    finally:
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        lines = ['# RustDesk Upstream Compatibility', '', '```json', json.dumps(report, indent=2), '```', '']
        (destination / 'report.md').write_text('\n'.join(lines))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as file:
                file.write('\n'.join(lines))
    return 0 if report['Overall'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
