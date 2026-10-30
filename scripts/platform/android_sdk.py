#!/usr/bin/env python3
"""Prepare reviewed Android SDK components before expensive native compilation."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import tempfile
import zipfile


def packages(tree, flutter):
    app = (tree / 'flutter/android/app/build.gradle').read_text()
    # desktop_drop requires API 33 independently of the application compile SDK.
    levels = {33}
    literals = re.findall(r'compileSdk(?:Version)?\s*(?:=\s*)?(\d+)', app)
    levels.update(map(int, literals))
    uses_flutter = bool(re.search(r'compileSdk(?:Version)?\s*(?:=\s*)?flutter\.compileSdkVersion', app))
    if uses_flutter:
        paths = [flutter / 'packages/flutter_tools/gradle/src/main/groovy/flutter.groovy',
                 flutter / 'packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt']
        matches = {int(x) for p in paths if p.is_file() for x in
                   re.findall(r'compileSdkVersion\s*(?::\s*Int\s*)?=\s*(\d+)', p.read_text())}
        if len(matches) != 1:
            raise ValueError('BUILD_COMPAT: cannot resolve Flutter compile SDK')
        levels.update(matches)
    if not literals and not uses_flutter:
        raise ValueError('BUILD_COMPAT: unrecognized Android compile SDK')
    if any(x < 21 or x > 99 for x in levels):
        raise ValueError('BUILD_COMPAT: invalid Android SDK level')
    tools = set(re.findall(r'buildToolsVersion\s*(?:=\s*)?["\x27]([0-9]+\.[0-9]+\.[0-9]+)["\x27]', app))
    return [f'platforms;android-{x}' for x in sorted(levels)] + [f'build-tools;{x}' for x in sorted(tools)]


def valid(sdk, package):
    kind, version = package.split(';')
    folder = sdk / kind / version
    if not (folder / 'source.properties').is_file():
        return False
    if kind == 'platforms':
        properties = (folder / 'source.properties').read_text()
        if not re.search(r'^AndroidVersion.ApiLevel\s*=\s*' + version.removeprefix('android-') + r'\s*$', properties, re.M):
            return False
        try:
            with zipfile.ZipFile(folder / 'android.jar') as archive:
                return bool(archive.namelist()) and archive.testzip() is None
        except (OSError, zipfile.BadZipFile):
            return False
    return all((folder / name).is_file() for name in ('aapt2', 'apksigner'))


def prepare(tree, flutter, sdk, output):
    sdk = sdk.resolve()
    manager = sdk / 'cmdline-tools/latest/bin/sdkmanager'
    if not manager.is_file():
        found = shutil.which('sdkmanager')
        if not found:
            raise ValueError('TOOLCHAIN: sdkmanager missing')
        manager = Path(found)
    selected = packages(tree, flutter)
    report = dict(schema='android-sdk-preflight-v1', packages=selected, attempts=[], result='FAIL')
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for attempt in range(1, 4):
            missing = [p for p in selected if not valid(sdk, p)]
            if not missing:
                report['result'] = 'PASS'
                return report
            # Remove only the exact invalid SDK component, never the whole SDK/cache.
            for package in missing:
                folder = sdk.joinpath(*package.split(';'))
                if folder.exists():
                    if folder.is_symlink() or not folder.resolve().is_relative_to(sdk):
                        raise ValueError('PROVENANCE: SDK component escapes SDK root')
                    shutil.rmtree(folder)
            # Fresh staging per attempt avoids reusing a truncated installer download.
            with tempfile.TemporaryDirectory(prefix='sdk-install-', dir=output.parent) as temp:
                staging = Path(temp).resolve()
                try:
                    result = subprocess.run([str(manager), '--sdk_root=' + str(staging), '--install', *missing],
                                            input='y\n'*100, text=True, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, timeout=300)
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = 'timeout'
                for package in missing:
                    if valid(staging, package):
                        destination = sdk.joinpath(*package.split(';'))
                        shutil.copytree(staging.joinpath(*package.split(';')), destination)
                # SDK manager accepts licenses in the staging SDK; retain these for Gradle.
                for license_file in (staging / 'licenses').glob('*'):
                    if license_file.is_file() and not license_file.is_symlink():
                        target = sdk / 'licenses' / license_file.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        accepted = set(license_file.read_text().split())
                        if target.exists():
                            accepted.update(target.read_text().split())
                        if not all(re.fullmatch('[0-9a-f]{40}', value) for value in accepted):
                            raise ValueError('PROVENANCE: invalid SDK license record')
                        target.write_text('\n'.join(sorted(accepted)) + '\n')
            remaining = [p for p in selected if not valid(sdk, p)]
            report['attempts'].append(dict(attempt=attempt, exit_code=code, invalid=remaining))
            print(f'Android SDK preflight attempt {attempt}: ' + ('PASS' if not remaining and code == 0 else 'FAIL'))
            if not remaining and code == 0:
                report['result'] = 'PASS'
                return report
            if attempt < 3:
                time.sleep(10 * attempt)
        raise ValueError('INFRASTRUCTURE: SDK_INSTALL_RETRY_EXHAUSTED')
    finally:
        output.write_text(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--flutter', type=Path, required=True)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('.work/target-diagnostic/android-sdk.json'))
    args = parser.parse_args()
    prepare(args.tree, args.flutter, args.sdk, args.output)


if __name__ == '__main__':
    main()
