#!/usr/bin/env python3
"""Execute named commands only after reviewing the exact upstream job signature."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from scripts.build import reliability
from scripts.platform.platform_adapter import check, render

STEPS = {
    ('macos', 'setup'): ['Install build runtime', 'Install NASM', 'Patch flutter', 'Workaround for flutter issue'],
    ('macos', 'build'): ['Build rustdesk'],
    ('android', 'deps'): ['Install vcpkg dependencies'],
    ('android', 'native'): ['Build rustdesk lib'],
    ('android', 'package'): ['Build rustdesk'],
}
FLUTTER_APK = re.compile(
    r'^([ \t]*)flutter build apk "--(?:release|debug|profile)" '
    r'--target-platform (?:android-arm64|android-arm|android-x64) --split-per-abi[ \t]*$',
    re.MULTILINE,
)


def android_package(script):
    """Wrap only the rendered, reviewed Flutter invocation for the selected ABI."""
    launcher = Path(reliability.__file__).resolve().with_name('flutter_apk.py')
    wrapper = shlex.join([sys.executable, str(launcher)])
    return FLUTTER_APK.sub(lambda match: match[1] + wrapper + match[0].lstrip()[len('flutter build apk'):], script)


def main():
    root, platform, arch, phase = sys.argv[1:]
    root = Path(root).resolve()
    profile, job = check(root, platform, arch)
    selected = STEPS[(platform, phase)]
    if (platform, phase) == ('android', 'deps') and any(
            step.get('name') == 'Check JNI natives are in ffi.FFI' for step in job['steps']):
        selected = ['Check JNI natives are in ffi.FFI', *selected]
    if (platform, arch, phase) == ('macos', 'aarch64', 'setup') and profile.get('macos_flutter344'):
        selected = ['Keep CocoaPods for Flutter 3.44 (arm64)', *(name for name in selected if name != 'Patch flutter')]
    if (platform, arch, phase) == ('macos', 'x86_64', 'build') and reliability.mode() == 'canary':
        code = reliability.run(
            reliability.CARGO, ['cargo', 'fetch', '--locked', '--target', 'x86_64-apple-darwin'], root,
            env={**os.environ, 'CARGO_NET_RETRY': '0', 'CARGO_NET_GIT_FETCH_WITH_CLI': 'true'},
        )
        if code:
            return reliability.exit_code(code)
    for name in selected:
        step = next(step for step in job['steps'] if step.get('name') == name)
        script = render(step['run'], profile).replace('/workspace', str(root))
        if platform == 'macos':
            # Official GNU sed spelling cannot be used with BSD sed on hosted macOS.
            script = script.replace('sed -i -e', "sed -i '' -e")
        if (platform, phase) == ('android', 'package') and reliability.mode() != 'off':
            script = android_package(script)
            code = subprocess.call(['bash', '-euo', 'pipefail', '-c', script], cwd=root)
            if code:
                return reliability.exit_code(code)
        else:
            subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=root, check=True)
    return 0


if __name__ == '__main__':
    result = main()
    if result:
        sys.exit(result)
