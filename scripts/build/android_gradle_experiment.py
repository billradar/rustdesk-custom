"""Compare online APK packaging with empty and seeded job-local Gradle homes."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from scripts.build.formal_validation import worker_identity

INIT = """
gradle.beforeProject { project ->
    if (project.path == ':' && project.rootDir.canonicalPath == System.getenv('BRF_FLUTTER_GRADLE_ROOT')) {
        project.configurations.matching { it.name == 'compileClasspath' }.all { configuration ->
            def started
            configuration.incoming.beforeResolve { started = System.nanoTime() }
            configuration.incoming.afterResolve {
                if (started != null) {
                    println("BRF_GRADLE_CLASSPATH_MS=" + ((System.nanoTime() - started).intdiv(1000000)))
                }
            }
        }
    }
}
"""
TRANSFER = re.compile(r'^Downloading https://(?:repo\.maven\.apache\.org|dl\.google\.com|'
                      r'maven\.google\.com|plugins\.gradle\.org)/\S+')
FLUTTER_PREFIX = re.compile(r'^\[\s*(?:[+-]?\d+\s*ms)?\]\s*')
CLASSPATH = re.compile(r'^BRF_GRADLE_CLASSPATH_MS=(\d+)$')
ASSEMBLE = re.compile(r"Running Gradle task 'assembleRelease'\.\.\.\s+([\d.]+)s")
PACKAGE_REPORT = Path('.work/native/package-report.json')


def seed_dependencies(cold, warm):
    source = cold / 'caches/modules-2'
    if not source.is_dir() or source.is_symlink() or any(path.is_symlink() for path in source.rglob('*')):
        raise ValueError('Expected a populated Gradle dependency cache without symlinks')
    shutil.copytree(source, warm / 'caches/modules-2',
                    ignore=shutil.ignore_patterns('*.lock', 'gc.properties'))


def sample(tree, directory):
    home = directory / 'gradle'
    with (home / 'gradle.properties').open('x') as options:
        options.write('org.gradle.logging.level=info\norg.gradle.daemon=false\norg.gradle.caching=false\n')
    (home / 'init.d').mkdir()
    (home / 'init.d/measure.gradle').write_text(INIT)
    flutter_gradle = Path(shutil.which('flutter')).parent.parent / 'packages/flutter_tools/gradle'
    env = {**os.environ, 'GRADLE_USER_HOME': str(home), 'PUB_CACHE': str(directory / 'pub'),
           'BRF_FLUTTER_GRADLE_ROOT': str(flutter_gradle.resolve(strict=True))}
    counters = {'included_compile_classpath_ms': [], 'assemble_release_seconds': [],
                'repository_download_log_lines': 0, 'maven_429_log_lines': 0}
    start = time.monotonic()
    command = [sys.executable, 'scripts/platform/platform_commands.py', str(tree), 'android', 'x86_64', 'package']
    with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, errors='replace') as process:
        for raw in process.stdout:
            print(raw, end='', flush=True)
            line = FLUTTER_PREFIX.sub('', raw.strip(), count=1)
            if match := CLASSPATH.fullmatch(line):
                counters['included_compile_classpath_ms'].append(int(match[1]))
            if match := ASSEMBLE.search(line):
                counters['assemble_release_seconds'].append(float(match[1]))
            counters['repository_download_log_lines'] += bool(TRANSFER.match(line))
            counters['maven_429_log_lines'] += ('repo.maven.apache.org/' in line
                                                and 'Received status code 429' in line)
        code = process.wait()
    counters['packaging_wall_seconds'] = round(time.monotonic() - start, 2)
    counters['exit_code'] = code
    if code:
        return counters, False
    subprocess.run([sys.executable, '-m', 'scripts.build.platform_ci_report',
                    str(tree), 'android', 'x86_64', 'standard'], check=True)
    counters['package_verification'] = 'PASS'
    return counters, True


def main():
    expected = {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_ACTIONS': 'true',
                'BUILD_CHANNEL': 'ci', 'BUILD_CONFIGURATION': 'TEST ONLY',
                'PLATFORM': 'android', 'PLATFORM_ARCH': 'x86_64', 'VARIANT': 'standard'}
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise ValueError('Only the Android x86_64 formal PR fixture may run this comparison')
    tree = Path(os.environ['PREPARED_SOURCE_DIR']).resolve()
    identity = worker_identity(tree, 'standard')
    flutter = tree / 'flutter'
    evidence = Path('.work/native/gradle-experiment.json')
    report = {'schema': 'brf-android-gradle-experiment-v1', 'source': identity, 'samples': {}}
    with tempfile.TemporaryDirectory(prefix='gradle-experiment-', dir=tree.parent) as temporary:
        scratch = Path(temporary)
        shutil.copytree(flutter, scratch / 'pristine-flutter', symlinks=True)
        cold = scratch / 'cold'
        (cold / 'gradle').mkdir(parents=True)
        warm = scratch / 'warm'
        try:
            report['samples']['cold'], passed = sample(tree, cold)
            if not passed:
                return report['samples']['cold']['exit_code']
            PACKAGE_REPORT.unlink()
            flutter.rename(scratch / 'cold-flutter')
            (tree / 'signed-apk').rename(scratch / 'cold-apk')
            (scratch / 'pristine-flutter').rename(flutter)
            seed_dependencies(cold / 'gradle', warm / 'gradle')
            report['samples']['warm'], passed = sample(tree, warm)
            return 0 if passed else report['samples']['warm']['exit_code']
        finally:
            evidence.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    sys.exit(main())
