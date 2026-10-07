#!/usr/bin/env python3
"""Canonical public release asset naming.

Standard is the default product and therefore has no variant token.
SOS is the only variant that carries the ``-sos`` token.
"""

def variant_suffix(variant):
    if variant == 'standard':
        return ''
    if variant == 'sos':
        return '-sos'
    raise ValueError('Unknown release variant: '+str(variant))

def windows_installer_name(version, variant, extension):
    ext = extension.lower().lstrip('.')
    if ext not in ('exe', 'msi'):
        raise ValueError('Unsupported Windows installer extension: '+ext)
    return f'rustdesk-{version}{variant_suffix(variant)}-windows-x86_64.{ext}'

def native_package_name(version, variant, platform, arch, package_name):
    """Normalize native package names into one canonical public name."""
    if platform not in ('android', 'linux', 'macos'):
        raise ValueError('Unsupported release platform: '+str(platform))
    tail = package_name.rsplit('/', 1)[-1]
    for prefix in (f'{variant}-rustdesk-{version}-', f'rustdesk-{version}-'):
        if tail.startswith(prefix):
            tail = tail[len(prefix):]
            break

    if tail.startswith(f'{arch}.'):
        payload = tail[len(arch):]
    else:
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
        payload = '-' + tail

    return f'rustdesk-{version}{variant_suffix(variant)}-{platform}-{arch}{payload}'
