"""Verify real DEB/RPM CI fixture packages without granting release qualification.

Do not call platform_package.create/validate: they deliberately reject fictional
build configuration. This code uses the existing ELF/DRM checks only and emits
a report, never an installable artifact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from scripts.platform.platform_package import architecture, validate_stock_linux_payload

PINNED_UPSTREAM = '51f94394ce61e1f3d26229565c326b2862cbdd1f'
DEB_ARCH = {'x86_64': 'amd64', 'aarch64': 'arm64'}
TEST_SERVER = 'test.invalid'


def run(*argv, cwd=None):
    return subprocess.check_output(argv, text=True, cwd=cwd).strip()


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_native(root, arch):
    validate_stock_linux_payload(root)
    libraries = list(root.rglob('librustdesk.so'))
    if len(libraries) != 1 or libraries[0].is_symlink():
        raise ValueError('PACKAGE: exactly one regular RustDesk ELF is required')
    data = libraries[0].read_bytes()
    architecture(data, 'linux', arch)
    if TEST_SERVER.encode() not in data:
        raise ValueError('PACKAGE: packaged ELF is not a fictional CI build')
    return hashlib.sha256(data).hexdigest()


def validate(tree, arch, variant):
    if (
        os.environ.get('BUILD_CONFIGURATION') != 'CI_PACKAGE_TEST'
        or os.environ.get('BUILD_CHANNEL') != 'ci'
        or os.environ.get('PATCHSET') != 'v4'
        or os.environ.get('GITHUB_ACTIONS') != 'true'
        or os.environ.get('GITHUB_EVENT_NAME') not in ('pull_request', 'workflow_dispatch')
        or os.environ.get('BUILD_FLAVOR', '') != ''
        or os.environ.get('RUSTDESK_ID_SERVER') != TEST_SERVER
        or os.environ.get('RUSTDESK_API_SERVER') != 'https://api.test.invalid'
        or os.environ.get('UPSTREAM_EXPECTED_SHA') != PINNED_UPSTREAM
        or variant not in ('standard', 'sos')
        or arch not in DEB_ARCH
        or run('git', '-C', str(tree), 'rev-parse', 'HEAD') != PINNED_UPSTREAM
    ):
        raise ValueError('BUILD_COMPAT: CI-only package verifier context forbidden')
    formal=None
    if os.environ.get('FORMAL_VALIDATION')=='true':
        from scripts.build.formal_validation import worker_identity
        formal=worker_identity(tree,variant)
    # The official Docker recipe builds this native release library and then
    # packages its Flutter bundle. Check the actual binary and archives.
    library = tree / 'target/release/liblibrustdesk.so'
    if not library.is_file() or library.is_symlink():
        raise ValueError('PACKAGE: official release library not found')
    architecture(library.read_bytes(), 'linux', arch)
    if TEST_SERVER.encode() not in library.read_bytes():
        raise ValueError('PACKAGE: native release binary has no fictional CI marker')
    debs = sorted(tree.glob('rustdesk*.deb'))
    rpms = sorted(tree.glob('rustdesk*.rpm'))
    if len(debs) != 1 or len(rpms) != 2:
        raise ValueError('PACKAGE: expected one DEB plus Fedora/SUSE RPM pair, got '
                         + str(len(debs)) + ' DEB and ' + str(len(rpms)) + ' RPM')
    info = []
    for fmt, packages in (('deb', debs), ('rpm', rpms)):
        for package in packages:
            if (not package.is_file() or package.is_symlink()
                    or package.stat().st_size < 1024):
                raise ValueError('PACKAGE: missing, empty or unsafe archive')
            with tempfile.TemporaryDirectory(prefix='rustdesk-ci-deb-rpm-') as td:
                unpacked = Path(td)
                if fmt == 'deb':
                    metadata_arch = run('dpkg-deb', '-f', str(package), 'Architecture')
                    metadata_name = run('dpkg-deb', '-f', str(package), 'Package')
                    if metadata_arch != DEB_ARCH[arch]:
                        raise ValueError('ARCH: DEB metadata does not match runner')
                    subprocess.run(['dpkg-deb', '-x', str(package), td], check=True)
                else:
                    metadata_arch = run('rpm', '-qp', '--qf', '%{ARCH}', str(package))
                    metadata_name = run('rpm', '-qp', '--qf', '%{NAME}', str(package))
                    if metadata_arch != arch:
                        raise ValueError('ARCH: RPM metadata does not match runner')
                    paths = run('rpm', '-qpl', str(package)).splitlines()
                    if not paths or any('..' in Path(path).parts for path in paths):
                        raise ValueError('PACKAGE: unsafe or empty RPM member list')
                    reader = subprocess.Popen(
                        ['rpm2cpio', str(package)], stdout=subprocess.PIPE)
                    try:
                        extracted = subprocess.run(
                            ['cpio', '-idm', '--no-absolute-filenames'],
                            stdin=reader.stdout, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, cwd=td, check=False)
                        reader.stdout.close()
                        if reader.wait() != 0 or extracted.returncode != 0:
                            raise ValueError('PACKAGE: RPM payload extraction failed')
                    finally:
                        if reader.poll() is None:
                            reader.kill()
                            reader.wait()
                if metadata_name != 'rustdesk':
                    raise ValueError('PACKAGE: unexpected package identity')
                packaged_elf_digest = assert_native(unpacked, arch)
            info.append({
                'format': fmt,
                'name': package.name,
                'architecture': metadata_arch,
                'sha256': checksum(package),
                'bytes': package.stat().st_size,
                'packaged_elf_sha256': packaged_elf_digest,
            })
    return {
        'schema': 'linux-v4-ci-package-smoke-v1',
        'result': 'PASS',
        'release_eligible': False,
        'qualification': 'FICTIONAL_CONFIGURATION_CI_ONLY',
        'upstream_sha': PINNED_UPSTREAM,
        'arch': arch,
        'variant': variant,
        'package_count': len(info),
        'packages': info,
        **({'formal_source_evidence':formal} if formal is not None else {}),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tree', type=Path, required=True)
    p.add_argument('--arch', choices=tuple(DEB_ARCH), required=True)
    p.add_argument('--variant', choices=('standard', 'sos'), required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = validate(a.tree.resolve(), a.arch, a.variant)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('CI package smoke PASS: 1 DEB + 2 RPM, ELF/architecture/no-DRM '
          'verified; not release eligible')


if __name__ == '__main__':
    main()
