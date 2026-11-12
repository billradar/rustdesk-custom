#!/usr/bin/env python3
"""Canonical public release asset naming.

Standard is the default product and therefore has no variant token.
SOS is the only variant that carries the ``-sos`` token.
"""
import re


def variant_suffix(variant):
    if variant == 'standard':
        return ''
    if variant == 'sos':
        return '-sos'
    raise ValueError('Unknown release variant: '+str(variant))

def windows_installer_name(version, variant, extension, arch="x86_64"):
    if arch not in ("x86_64", "aarch64"):
        raise ValueError("Unsupported Windows architecture")
    ext = extension.lower().lstrip('.')
    if ext not in ('exe', 'msi'):
        raise ValueError('Unsupported Windows installer extension: '+ext)
    return f'rustdesk-{version}{variant_suffix(variant)}-windows-{arch}.{ext}'

def native_package_name(version, variant, platform, arch, package_name, *, legacy_rpm=False):
    """Normalize public names; v1/v2 callers explicitly retain legacy RPM suffixes."""
    if platform not in ('android', 'linux', 'macos'):
        raise ValueError('Unsupported release platform: '+str(platform))
    tail = package_name.rsplit('/', 1)[-1]
    for prefix in (f'{variant}-rustdesk-{version}-', f'rustdesk-{version}-'):
        if tail.startswith(prefix):
            tail = tail[len(prefix):]
            break

    prefixes = (
        f'{variant}-{platform}-{arch}-',
        f'{platform}-{arch}-{variant}-{platform}-{arch}-',
        f'{platform}-{arch}-{platform}-{arch}-',
        f'{platform}-{arch}-',
        f'{arch}-',
        f'{variant}-',
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if tail.startswith(prefix):
                tail = tail[len(prefix):]
                changed = True
                break
    for marker in (f'-{variant}-{platform}-{arch}-', f'-{platform}-{arch}-'):
        if marker in tail:
            tail = tail.replace(marker, '-', 1)
    if not tail:
        raise ValueError('Package name has no payload suffix: '+package_name)
    # An extension can follow the architecture directly in raw or canonical
    # names. Strip this form too, making normalization idempotent for DEBs.
    for prefix in (f'{variant}-{platform}-{arch}', f'{platform}-{arch}', arch):
        if tail.startswith(prefix+'.'):
            payload = tail[len(prefix):]
            break
    else:
        payload = '-' + tail

    if platform == 'linux' and tail.endswith('.rpm') and not legacy_rpm:
        # RPM's internal Release/Architecture fields are not public selectors.
        # Keep only the package family; reject an unexpected/mismatched suffix.
        if payload not in ('.rpm', '-suse.rpm'):
            match = re.fullmatch(r'-[0-9]+\.' + re.escape(arch) + r'(-suse)?\.rpm', payload)
            if match is None:
                raise ValueError('Unexpected RPM release/architecture suffix: ' + package_name)
            payload = '-suse.rpm' if match.group(1) else '.rpm'

    return f'rustdesk-{version}{variant_suffix(variant)}-{platform}-{arch}{payload}'
