"""Shared Patchset content-version inputs and build-policy provenance."""
import hashlib
import os
import re
from pathlib import Path
from scripts.upstream.patchset_version import current, SCHEMA

ROOT = Path(__file__).resolve().parents[2]


def policy_digest(root=ROOT):
    # Conservative repository-controlled inputs: changing packaging, validation,
    # toolchains, signing profiles or a build workflow requires identity review.
    paths = set()
    for directory in ('scripts', 'metadata/build', 'metadata/platform', 'metadata/signing', '.github/actions'):
        for path in (root / directory).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc' and '_contract.' not in path.name:
                paths.add(path)
    for path in (root / '.github/workflows').glob('*.yml'):
        if path.name in ('tag.yml','nightly.yml','prepare-source.yml','wayland.yml') or path.name.startswith('build'):
            paths.add(path)
    paths.add(root / 'requirements.txt')
    digest = hashlib.sha256(b'custom-build-policy-v2\0')
    # Explicit relative POSIX ordering must also agree on case-insensitive hosts.
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix().encode('utf-8')):
        if path.is_symlink():
            raise ValueError('Nonregular build policy input')
        raw = path.read_bytes()
        # Git's Windows checkout conversion changes UTF-8 text CRLF/LF only.
        # Preserve binary inputs, BOMs, lone CRs and all other content exactly.
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError:
            pass
        else:
            if b'\0' not in raw:
                raw = raw.replace(b'\r\n', b'\n')
        digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0' + raw)
    return digest.hexdigest()


def inputs(patchset):
    data = current(patchset)
    return dict(patchset_version=f'{patchset}.{data["revision"]}',
                version_semantics=SCHEMA, build_policy_sha256=policy_digest())


def notes(patchset, *, nightly=False):
    data = current(patchset)
    return render_notes(data,nightly=nightly)


def render_notes(data, *, nightly=False, repository=None, source_ref=None):
    patchset=data['id']
    entry = data['versioning']['history'][-1]
    lines = [f'## Patchset {patchset}.{data["revision"]}', '',
             'RustDesk upstream version changes and Patchset content revisions are independent.', '',
             '### Current included customizations', '']
    for folder, features in data['versioning']['features'].items():
        lines += [f'- {folder.title()}: ' + feature for feature in features]
    lines += ['', '### Changes in this custom revision', '']
    if entry['kind']=='content-change':
        for category,items in entry['categories'].items():
            if category not in ('Compatibility',):
                lines += [f'- {category}: {item}' for item in items]
    else:
        lines += ['The existing customizations above are included in this build.']
    if entry['kind']=='content-change':
        for item in entry['categories'].get('Compatibility',[]):
            lines += ['- Compatibility: '+item]
    repository=repository or os.environ.get('GITHUB_REPOSITORY','billradar/rustdesk-custom')
    source_ref=source_ref or os.environ.get('GITHUB_SHA','')
    if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) and re.fullmatch(r'[0-9a-f]{40}',source_ref):
        lines += ['',f'[Full patch history](https://github.com/{repository}/blob/{source_ref}/patchsets/{patchset}/CHANGELOG.md)']
    return '\n'.join(lines)+'\n'
