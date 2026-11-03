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


def require_cutover():
    value = json.loads(CUTOVER.read_text())
    # A metadata-only change must never activate production admission.
    # A separately reviewed migration must establish and verify the complete
    # evidence-bound activation protocol before replacing this fail-closed guard.
    if value.get('schema') != 'patchset-cutover-v1':
        raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: invalid cutover schema')
    blockers = value.get('blockers')
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: invalid blocker inventory')
    # Activation requires an explicit, independently committed evidence certificate.
    # A status flip or environment variable alone cannot authorize new builds.
    if value.get('status') == 'ACTIVE' and not blockers:
        certificate = value.get('activation_evidence')
        if not isinstance(certificate, dict) or set(certificate) != {'path', 'sha256'}:
            raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: missing activation evidence')
        relative = certificate['path']
        expected = certificate['sha256']
        if (not isinstance(relative, str) or not relative.startswith('metadata/release/attestations/')
                or '..' in Path(relative).parts or Path(relative).is_absolute()
                or not isinstance(expected, str) or len(expected) != 64
                or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: invalid evidence reference')
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: evidence digest mismatch')
        evidence = json.loads(path.read_text())
        required = {'schema', 'decision', 'v2_only', 'journal_reconciled',
                    'workers_quiescent', 'releases_inventoried', 'version_gate_passed'}
        if (not isinstance(evidence, dict) or not required.issubset(evidence)
                or evidence['schema'] != 'content-v2-activation-attestation-v1'
                or evidence['decision'] != 'GO'
                or any(evidence[k] is not True for k in required - {'schema', 'decision'})):
            raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: incomplete activation evidence')
        return
    raise ValueError('PATCHSET_CUTOVER_REVIEW_REQUIRED: ' + ', '.join(blockers))


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
