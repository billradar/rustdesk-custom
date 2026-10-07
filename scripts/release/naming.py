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
    """Normalize an upstream package into the public RustDesk asset name."""
    if platform not in ('android', 'linux', 'macos'):
        raise ValueError('Unsupported native release platform: '+str(platform))
    tail = package_name
    prefix = f'{variant}-rustdesk-{version}-'
    if tail.startswith(prefix):
        tail = tail[len(prefix):]
    arch_prefix = f'{arch}-'
    if tail.startswith(arch_prefix):
        tail = tail[len(arch_prefix):]
    elif tail.startswith(f'{arch}.'):
        # Upstream may encode an extension directly after the architecture.
        # Strip the architecture and separator to avoid names such as x86_64-.deb.
        tail = tail[len(arch):].lstrip('-.')
    return f'rustdesk-{version}{variant_suffix(variant)}-{platform}-{arch}-{tail}'
