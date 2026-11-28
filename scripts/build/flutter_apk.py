"""Invoke the approved Android ABI command at the dependency recovery boundary."""

import argparse
import os
from pathlib import Path
import sys

import reliability


def main():
    parser = argparse.ArgumentParser()
    build = parser.add_mutually_exclusive_group(required=True)
    for value in ('debug', 'profile', 'release'):
        build.add_argument('--' + value, dest='build', action='store_const', const=value)
    parser.add_argument('--target-platform', required=True, choices=('android-arm', 'android-arm64', 'android-x64'))
    parser.add_argument('--split-per-abi', required=True, action='store_true')
    args = parser.parse_args()
    root = Path.cwd()
    output = root / 'build/app/outputs'
    # Compile classpath resolution fails before APK creation. A prior or partial
    # output is grounds to suppress replay, with no cleanup of Gradle state.
    def output_absent():
        return not output.exists() and not output.is_symlink()

    clean_start = output_absent()
    command = ['flutter', 'build', 'apk', '--' + args.build, '--target-platform', args.target_platform, '--split-per-abi']
    if os.environ.get('BRF_GRADLE_EXPERIMENT') == '1' and os.environ.get('BRF_FLUTTER_GRADLE_ROOT'):
        # Flutter otherwise passes -q to Gradle, hiding dependency downloads.
        command.append('--verbose')
    return reliability.exit_code(reliability.run(
        reliability.MAVEN, command,
        root, replay_safe=lambda: clean_start and output_absent(),
    ))


if __name__ == '__main__':
    sys.exit(main())
