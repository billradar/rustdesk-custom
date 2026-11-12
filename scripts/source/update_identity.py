"""Embed a non-secret client identity before prepared-source inventory is frozen."""
import json
import os
import re
from pathlib import Path


def write_identity(tree, *, repository, version, sha, variant, run, channel, revision=""):
    if (not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}", repository)
            or repository.rsplit('/', 1)[-1] in ('.', '..')
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or variant not in ("standard", "sos")
            or not re.fullmatch(r"[1-9][0-9]*", str(run))
            or channel not in ("ci", "stable", "nightly")):
        raise ValueError("Invalid client update source identity")
    if channel == "stable":
        if not re.fullmatch(r"v[1-9][0-9]*\.[1-9][0-9]*", revision):
            raise ValueError("Stable client requires the preflight patch revision")
    elif revision:
        raise ValueError("Non-release builds must not claim a Stable revision")
    from scripts.upstream.patchsets import patchset_for_version
    from scripts.release.content import inputs
    content = inputs(patchset_for_version(version, channel=channel))
    if channel == 'stable' and revision != content['patchset_version']:
        raise ValueError('Stable revision differs from version-controlled Patchset content')
    data = dict(repository=repository, version=version, revision=revision or None, upstream_sha=sha,
                variant=variant, build_run=str(run), channel=channel, **content)
    data.update(repository_id=os.environ.get('GITHUB_REPOSITORY_ID'),repository_owner_id=os.environ.get('GITHUB_REPOSITORY_OWNER_ID'))
    if content['patchset_version'].startswith('v3.') and any(
            not re.fullmatch(r'[1-9][0-9]*',str(data[key] or ''))
            for key in ('repository_id','repository_owner_id')):
        raise ValueError('Current updater requires numeric GitHub repository and owner IDs')
    destination = Path(tree) / "src/custom_update/build.json"
    if not destination.is_file() or destination.is_symlink():
        raise ValueError("Client update patch must be applied before identity injection")
    about = Path(tree) / ABOUT_PATH
    if not about.is_file() or about.is_symlink():
        raise ValueError("About identity patch must be applied before identity injection")
    destination.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    about.write_text(about_source(data), encoding='utf-8')
    return data


ABOUT_PATH = 'flutter/lib/common/custom_about_identity.dart'


def about_source(identity, *, unattended=False):
    version = identity['version'] + '-custom'
    if identity.get('revision'):
        version += '.' + identity['revision']
    elif identity.get('patchset_version'):
        version += '.' + identity['patchset_version'] + '-' + identity['channel']
    variant = {'standard': 'Standard', 'sos': 'SOS'}[identity['variant']]
    return ('// Generated display identity; internal versions are unchanged.\n'
            'const customAboutVersion = ' + json.dumps(version) + ';\n'
            'const customAboutVariant = ' + json.dumps(variant) + ';\n'
            'const customAboutWayland = ' + ('true' if unattended else 'false') + ';\n')


def verify_about_identity(tree, *, unattended=False):
    tree = Path(tree)
    identity = json.loads((tree / 'src/custom_update/build.json').read_text(encoding='utf-8'))
    about = tree / ABOUT_PATH
    if about.is_symlink() or about.read_text(encoding='utf-8') != about_source(identity, unattended=unattended):
        raise ValueError('PROVENANCE: About display differs from actual build identity')


def enable_wayland_about(tree, variant):
    tree = Path(tree)
    verify_about_identity(tree)
    identity = json.loads((tree / 'src/custom_update/build.json').read_text(encoding='utf-8'))
    if variant not in ('standard', 'sos') or identity['variant'] != variant:
        raise ValueError('PROVENANCE: About Wayland source variant mismatch')
    (tree / ABOUT_PATH).write_text(about_source(identity, unattended=True), encoding='utf-8')
