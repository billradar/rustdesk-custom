#!/usr/bin/env python3
"""Static review of upstream build adapter drift. Does not approve signatures."""
import argparse
import json
import subprocess
from pathlib import Path

from scripts.build.build_adapter import CRITICAL_FILES, inspect as inspect_build
from scripts.platform.platform_adapter import (
    adapt_stock_linux_recipe, guard_stock_linux_drm_recipe,
    inspect as inspect_platform, render
)

REVIEWED = '6aec3069aec486ad7df07429a0a1ee411fc8d73a'
CANDIDATE = '9724512429b053be04cdb843345e99ddcccdb80e'
NEW_MAIN = '51f94394ce61e1f3d26229565c326b2862cbdd1f'
EXPECTED_CANDIDATE_SIGNATURE = '1af2302002908d0bbc7e7d3f6cc3ba20db6de1edd4d2ecd733e470c1dabb4741'


def checked_sha(tree, wanted):
    actual = subprocess.check_output(
        ['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != wanted:
        raise ValueError(f'Incorrect official source: {actual}, expected {wanted}')


def stock_recipe(tree, arch='x86_64'):
    profile, job = inspect_platform(tree, 'linux', arch)
    step = next(s for s in job['steps']
                if s.get('name') == 'Build rustdesk' and 'with' in s)
    return render(step['with']['run'], profile)


def review(old, candidate, current):
    for tree, sha in ((old, REVIEWED), (candidate, CANDIDATE), (current, NEW_MAIN)):
        checked_sha(tree, sha)
    previous, previous_critical = inspect_build(old)
    candidate_profile, candidate_critical = inspect_build(candidate)
    latest, latest_critical = inspect_build(current)
    if candidate_profile['signature'] != EXPECTED_CANDIDATE_SIGNATURE:
        raise ValueError('Candidate critical-interface signature differs from previous staging observation')
    if latest['signature'] != candidate_profile['signature']:
        raise ValueError('New main differs from the already inspected v4 source adapter')
    if latest_critical != candidate_critical:
        raise ValueError('New main changed a critical job, toolchain, or file')
    if previous_critical['windows_job'] != latest_critical['windows_job']:
        raise ValueError('Windows job changed: review separately')
    if previous_critical['tools'] != latest_critical['tools']:
        raise ValueError('Reviewed toolchain changed: review separately')
    changed = sorted(
        p for p in CRITICAL_FILES
        if previous_critical['files'][p] != latest_critical['files'][p]
    )
    if changed != ['build.py']:
        raise ValueError(f'Unexpected change in critical files: {changed}')
    old_text = (old / 'build.py').read_text()
    new_text = (current / 'build.py').read_text()
    required = (
        "'--drm'" in old_text
        and "'--no-drm'" in new_text
        and 'not args.no_drm' in new_text
        and "features.append('drm')" in new_text
        and "features.append('drm-wake')" in new_text
        and 'Conflicts: rustdesk-unattended-wayland' in new_text
        and 'Replaces: rustdesk-unattended-wayland' in new_text
        and 'DRM_PACKAGE_NAME =' in old_text
        and 'DRM_PACKAGE_NAME =' not in new_text
    )
    if not required:
        raise ValueError('Observed Linux DRM default or package identity differs from reviewed findings')
    if not guard_stock_linux_drm_recipe(old, stock_recipe(old)):
        raise AssertionError('Legacy stock Linux recipe check did not pass')
    try:
        guard_stock_linux_drm_recipe(current, stock_recipe(current))
    except ValueError as exc:
        if 'stock Linux recipe enables DRM' not in str(exc):
            raise ValueError('New Linux source rejected for an unexpected reason') from exc
        rejected = str(exc)
    else:
        raise ValueError('FAIL: new upstream Linux stock recipe silently admits DRM')
    # A safe stock recipe must disable capture at *both* Cargo compile and
    # build.py packaging. The same reviewed transform serves x64 and ARM64.
    transformed = {}
    for arch in ('x86_64', 'aarch64'):
        original = stock_recipe(current, arch)
        adapted = adapt_stock_linux_recipe(current, original)
        guard_stock_linux_drm_recipe(current, adapted)
        if adapted == original:
            raise ValueError('Latest Linux stock recipe was not adapted')
        expected_features = 'hwcodec,flutter,unix-file-copy-paste'
        actual_features = subprocess.check_output(
            ['python3', 'build.py', '--flutter', '--hwcodec',
             '--unix-file-copy-paste', '--no-drm', '--print-features'],
            cwd=current, text=True).strip()
        if actual_features != expected_features:
            raise ValueError('Official no-DRM feature resolver no longer matches stock Cargo features')
        if 'STOCK_FEATURES=$(python3 ./build.py' not in adapted:
            raise ValueError('Stock recipe does not verify upstream feature resolver before compiling')
        if '--features hwcodec,flutter,unix-file-copy-paste --release' not in adapted:
            raise ValueError('Native stock Cargo features are not explicitly DRM-free')
        if '--no-drm' not in adapted or 'check_rpm_drm "$name"' in adapted:
            raise ValueError('Stock packaging still inherits DRM')
        if '--features hwcodec,flutter,unix-file-copy-paste,drm' in adapted:
            raise ValueError('Stock native build still compiles DRM')
        transformed[arch] = {'stock_recipe_safe': True,
                             'native_cargo_drm_disabled': True,
                             'package_no_drm_explicit': True,
                             'stale_library_refused': 'stock Linux source contains prebuilt libdrmtap' in adapted,
                             'upstream_feature_resolver': actual_features}
    if not all(p['stale_library_refused'] for p in transformed.values()):
        raise ValueError('Stock RPM prebuilt library contamination is unchecked')
    return {
        'kind': 'non-approving-static-build-interface-review',
        'reviewed_sha': REVIEWED,
        'candidate_sha': CANDIDATE,
        'new_main_sha': NEW_MAIN,
        'candidate_signature': candidate_profile['signature'],
        'new_main_signature': latest['signature'],
        'changed_critical_files_from_reviewed': changed,
        'windows_job_unchanged': True,
        'toolchain_unchanged': True,
        'linux_drm_default_changed': True,
        'ordinary_linux_recipe_guard': rejected,
        'adapted_stock_linux': transformed,
        'approved_adapter_signature': False,
        'stable_release_allowed': False,
        'decision': 'HOLD: separate source/profile approval, DRM packaging compatibility and native target tests required',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = review(args.old, args.candidate, args.current)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
