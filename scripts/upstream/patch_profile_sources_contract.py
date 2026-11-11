"""Offline integration checks against supplied, clean immutable upstream snapshots."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from scripts.upstream import patchsets
from scripts.validation.compatibility import contracts

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = '05b9f2d8919b5cdfaa0bb3280601a02881556a42'
STABLE = '23e5bb471a040d62f0a6ad52591fb30784265b73'
POSITION = 'flutter/lib/desktop/widgets/windows_cm_window_position.dart'
CHAT = 'flutter/lib/models/chat_model.dart'


def git(tree, *args):
    return subprocess.check_output(['git', '-C', str(tree), *args], text=True).strip()


def verify_source(tree, sha):
    if git(tree, 'rev-parse', 'HEAD') != sha or git(tree, 'status', '--porcelain', '--ignore-submodules=none'):
        raise ValueError('Integration source must be clean and match exact snapshot SHA')
    expected = git(tree, 'rev-parse', 'HEAD:libs/hbb_common')
    if git(tree / 'libs/hbb_common', 'rev-parse', 'HEAD') != expected:
        raise ValueError('Integration submodule identity mismatch')


def exercise(source, version, sha, name, channel):
    verify_source(source, sha)
    selection = patchsets.require_selection(version, name, channel)
    result = dict(upstream_sha=sha, upstream_version=version, **selection, variants={})
    with tempfile.TemporaryDirectory(prefix='patch-profile-source-') as temp:
        for variant in ('standard', 'sos'):
            tree = Path(temp) / variant
            shutil.copytree(source, tree, symlinks=True)
            applied = subprocess.run(['bash', str(ROOT / 'scripts/source/apply_patches.sh'), str(tree), variant],
                                     env=dict(os.environ, PATCHSET=name, BUILD_CHANNEL=channel),
                                     capture_output=True, text=True)
            if applied.returncode:
                raise ValueError(applied.stdout + applied.stderr)
            order = [line.removeprefix('Checking ') for line in applied.stdout.splitlines()
                     if line.startswith('Checking ')]
            expected = [p.name for p in sorted((ROOT / 'patchsets' / name / 'common').glob('*.patch'))]
            if variant == 'sos':
                expected += [p.name for p in sorted((ROOT / 'patchsets' / name / 'sos').glob('*.patch'))]
            if order != expected:
                raise ValueError('Common/SOS patch order changed')
            result['variants'][variant] = dict(patch_order=order, git_apply_check='PASS',
                                               contracts=contracts(tree, variant, name))
            result['variants'][variant]['native_helper_compile'] = 'NOT_RUN (rustc unavailable)'
            if shutil.which('rustc'):
                subprocess.run(['bash', '-c',
                    'source scripts/validation/test_config.sh; '
                    'python3 scripts/source/verify_source.py "$1" "$2" --automation',
                    'native-helper', str(tree), variant], cwd=ROOT, check=True,
                    env=dict(os.environ, PATCHSET=name, PYTHONPATH=str(ROOT)),
                    stdout=subprocess.DEVNULL)
                result['variants'][variant]['native_helper_compile'] = 'PASS'
            if name == 'v3':
                if (tree / POSITION).read_bytes() != (source / POSITION).read_bytes():
                    raise ValueError('Upstream Windows DPI helper changed')
                original = (source / CHAT).read_text()
                restored = (tree / CHAT).read_text().replace(
                    '    if (desktopType == DesktopType.cm && !cmIsVisible) return false;\n', '')
                start, end = restored.index('  toggleCMSidePage() async {'), restored.index('  changeCurrentKey(')
                restored = restored[:start] + restored[start:end].replace(
                    'await showCmWindow();', 'await windowManager.show();') + restored[end:]
                if restored != original:
                    raise ValueError('Unexpected upstream chat/DPI changes outside visibility hooks')
                result['variants'][variant]['upstream_dpi_preservation'] = 'PASS'
    return result


def baseline_conflict(source):
    # Audit old bytes directly; production routing intentionally disallows this
    # version/generation combination before it can modify any source.
    with tempfile.TemporaryDirectory(prefix='patch-profile-conflict-') as temp:
        tree = Path(temp) / 'source'
        shutil.copytree(source, tree, symlinks=True)
        for patch in sorted((ROOT / 'patchsets/v2/common').glob('*.patch')):
            target = tree / 'libs/hbb_common' if patch.name == '0001-hbb-server-defaults.patch' else tree
            check = subprocess.run(['git', '-C', str(target), 'apply', '--check', str(patch)],
                                   capture_output=True, text=True)
            if check.returncode:
                if patch.name != '0004-cm-background-window.patch':
                    raise ValueError('Unexpected baseline conflict: ' + check.stderr)
                return dict(patch=patch.name, result='EXPECTED_CONFLICT', diagnostic=check.stderr.strip())
            subprocess.run(['git', '-C', str(target), 'apply', str(patch)], check=True)
    raise ValueError('Expected old v2 CM context conflict was not reproduced')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stable', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    args = parser.parse_args()
    results = [exercise(args.stable.resolve(), '1.5.1', STABLE, 'v2', 'stable'),
               exercise(args.candidate.resolve(), '1.5.3', CANDIDATE, 'v3', 'ci')]
    print(json.dumps(dict(result='PASS', snapshots=results,
                          old_v2_candidate=baseline_conflict(args.candidate.resolve())), indent=2))
