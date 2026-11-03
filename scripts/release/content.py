"""Shared content-version inputs, conservative build policy and cutover guard."""
import hashlib
import json
from pathlib import Path
from scripts.upstream.patchset_version import current, SCHEMA

ROOT = Path(__file__).resolve().parents[2]
CUTOVER = ROOT / 'metadata/release/patchset-cutover.json'


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
    digest = hashlib.sha256(b'custom-build-policy-v1\0')
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError('Nonregular build policy input')
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    return digest.hexdigest()


def inputs(patchset):
    data = current(patchset)
    return dict(patchset_version=f'{patchset}.{data["revision"]}',
                version_semantics=SCHEMA, build_policy_sha256=policy_digest())


def require_cutover():
    value = json.loads(CUTOVER.read_text())
    # This staged patch deliberately has no boolean/Environment bypass. A later
    # reviewed migration must implement and verify a quiescent reconciliation.
    raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: ' + ', '.join(value['blockers']))


def notes(patchset, *, nightly=False):
    data = current(patchset)
    entry = data['versioning']['history'][-1]
    lines = [f'## Patchset {patchset}.{data["revision"]}', '',
             'RustDesk upstream version changes and Patchset content revisions are independent.', '',
             '### Current included customizations', '']
    for folder, features in data['versioning']['features'].items():
        lines += [f'- {folder.title()}: ' + feature for feature in features]
    lines += ['', '### Recorded Patchset revision delta', '',
              ('This Nightly records the current revision; these are not claims of new changes in this build.' if nightly else
               'This is the recorded revision delta, not a claim that every feature was added in this release.'), '',
              'Kind: ' + entry['kind'], '', 'Reason: ' + entry['reason'], '']
    for category, items in entry['categories'].items():
        lines += [f'- {category}: {item}' for item in items]
    lines += ['', 'References: ' + ', '.join(entry['references']), '',
              'Upstream compatibility: ' + entry['compatibility'], '',
              'Known limitations: ' + entry['limitations'], '']
    for folder in ('common', 'sos'):
        lines += [f'- {folder.title()} Patch Hash: `{data["hashes"][folder]}`',
                  f'- {folder.title()} before: `{entry["before"][folder]}`; after: `{entry["after"][folder]}`']
    return '\n'.join(lines) + '\n'
