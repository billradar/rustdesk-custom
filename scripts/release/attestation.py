"""Strict release inventory, covered by a GitHub/Sigstore build attestation.

Internal source/build checksum manifests are a separate contract. Public Releases
use these two JSON files exclusively, with no SHA256SUMS fallback.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

MANIFEST = 'update-manifest.json'
BUNDLE = 'release-attestation.json'
SCHEMA = 'rustdesk-release-manifest-v1'
PREDICATE = 'https://slsa.dev/provenance/v1'
REPOSITORY = 'billradar/rustdesk-custom'
LIMIT = 1024 * 1024


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field: ' + key)
        result[key] = value
    return result


def loads(raw):
    if len(raw) > LIMIT:
        raise ValueError('Release manifest exceeds size limit')
    value = json.loads(raw, object_pairs_hook=_object)
    validate(value)
    return value


def validate(value):
    if not isinstance(value, dict) or value.get('schema') != SCHEMA:
        raise ValueError('Invalid release manifest schema')
    if value.get('repository') != REPOSITORY or value.get('channel') not in ('stable', 'nightly'):
        raise ValueError('Invalid release manifest repository/channel')
    for key, length in [('custom_repository_sha', 40), ('upstream_sha', 40),
                        ('common_patch_hash', 64), ('sos_patch_hash', 64)]:
        if not re.fullmatch('[0-9a-f]{'+str(length)+'}', str(value.get(key, ''))):
            raise ValueError('Invalid release manifest identity: ' + key)
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', str(value.get('upstream_version', ''))):
        raise ValueError('Invalid release manifest version')
    if not re.fullmatch(r'v[1-9][0-9]*', str(value.get('patchset', ''))):
        raise ValueError('Invalid release manifest patchset')
    if not re.fullmatch(r'[1-9][0-9]*', str(value.get('build_run', ''))):
        raise ValueError('Invalid release manifest build run')
    if value.get('qualification') != 'PASS':
        raise ValueError('Release manifest is not qualified')
    revision = value.get('patch_revision')
    if value['channel'] == 'stable':
        if not re.fullmatch(re.escape(value['patchset'])+r'\.[1-9][0-9]{0,5}', str(revision)):
            raise ValueError('Invalid Stable manifest patch revision')
    elif revision is not None:
        raise ValueError('Nightly manifest cannot claim a Stable revision')
    assets = value.get('assets')
    if not isinstance(assets, list) or not 1 <= len(assets) <= 256:
        raise ValueError('Invalid release manifest assets')
    names = set(); selectors = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError('Invalid release manifest asset')
        name = asset.get('name', '')
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,254}', name)
                or name in (MANIFEST, BUNDLE, 'SHA256SUMS')):
            raise ValueError('Unsafe release manifest asset name')
        if (type(asset.get('size')) is not int or asset['size'] <= 0
                or not re.fullmatch('[0-9a-f]{64}', str(asset.get('sha256', '')))):
            raise ValueError('Invalid release manifest asset digest/size')
        platform = asset.get('os'); arch = asset.get('arch'); variant = asset.get('variant')
        flavor = asset.get('flavor'); package = asset.get('package')
        formats = {'windows': ('exe', 'msi'), 'linux': ('deb', 'rpm', 'suse-rpm'),
                   'macos': ('dmg',), 'android': ('apk',)}
        if (platform not in formats or arch not in ('x86_64', 'aarch64', 'armv7')
                or variant not in ('standard', 'sos') or package not in formats[platform]
                or flavor not in ('ordinary', 'unattended-wayland')
                or (flavor == 'unattended-wayland' and (platform != 'linux' or package != 'deb'))
                or (platform == 'android' and variant != 'standard')
                or (arch == 'armv7' and platform != 'android')
                or not name.endswith('.'+('rpm' if package == 'suse-rpm' else package))):
            raise ValueError('Invalid release manifest package selector')
        selector = (platform, arch, variant, flavor, package)
        if name in names or selector in selectors:
            raise ValueError('Duplicate release manifest name/selector')
        names.add(name); selectors.add(selector)
    return value


def write(directory, channel, entries, info, report):
    """Build deterministic metadata only from already validated package identities."""
    if report.get('result') != 'PASS':
        raise ValueError('Cannot attest an incomplete release aggregate')
    value = dict(schema=SCHEMA, repository=os.environ.get('GITHUB_REPOSITORY', ''),
                 channel=channel, upstream_version=info['upstream_version'],
                 upstream_sha=info['upstream_sha'], custom_repository_sha=info['custom_repository_sha'],
                 patchset=info['patchset'], common_patch_hash=info['common_patch_hash'],
                 sos_patch_hash=info['sos_patch_hash'], build_run=str(os.environ['GITHUB_RUN_ID']),
                 patch_revision=info.get('patch_revision') if channel == 'stable' else None,
                 qualification='PASS', runtime_ui='NOT TESTED', real_remote_session='NOT TESTED',
                 assets=sorted(entries, key=lambda x: x['name']))
    validate(value)
    directory = Path(directory)
    expected = {a['name']: (a['size'], a['sha256']) for a in value['assets']}
    actual = {p.name: (p.stat().st_size, sha(p)) for p in directory.iterdir() if p.is_file()}
    if actual != expected:
        raise ValueError('Release manifest does not exactly cover staged packages')
    (directory / MANIFEST).write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')
    return value


def entry(path, info):
    platform = info['platform'].split('-')[0]
    package = path.suffix[1:].lower()
    if package == 'rpm' and path.name.endswith('-suse.rpm'):
        package = 'suse-rpm'
    return dict(name=path.name, size=path.stat().st_size, sha256=sha(path),
                os=platform, arch=info['architecture'], variant=info['variant'],
                flavor=info.get('build_flavor') or 'ordinary', package=package,
                signing_status=info.get('signed_status', 'NOT ENABLED'))


def verify_signature(manifest, bundle, value):
    """Use a maintained Sigstore verifier, never decode-and-trust the DSSE payload."""
    workflow = 'tag.yml' if value['channel'] == 'stable' else 'nightly.yml'
    subprocess.run(['gh', 'attestation', 'verify', str(manifest), '--bundle', str(bundle),
                    '--repo', REPOSITORY, '--signer-workflow', REPOSITORY+'/.github/workflows/'+workflow,
                    '--source-ref', 'refs/heads/main', '--source-digest', value['custom_repository_sha'],
                    '--predicate-type', PREDICATE, '--deny-self-hosted-runners'],
                   check=True, capture_output=True, text=True, timeout=120)


def verify_local(directory, channel=None, bundle=None):
    directory = Path(directory)
    manifest = directory / MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('Release update manifest missing or unsafe')
    if manifest.stat().st_size > LIMIT:
        raise ValueError('Release manifest exceeds size limit')
    value = loads(manifest.read_bytes())
    if channel is not None and value['channel'] != channel:
        raise ValueError('Release manifest channel mismatch')
    for key, env in [('custom_repository_sha', 'GITHUB_SHA'), ('upstream_sha', 'UPSTREAM_EXPECTED_SHA'),
                     ('build_run', 'GITHUB_RUN_ID'), ('patchset', 'PATCHSET')]:
        if os.environ.get(env) and str(value[key]) != os.environ[env]:
            raise ValueError('Release manifest identity mismatch: '+key)
    expected = {a['name']: (a['size'], a['sha256']) for a in value['assets']}
    paths = list(directory.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError('Unsafe release asset directory')
    actual = {p.name: (p.stat().st_size, sha(p)) for p in paths if p.name not in (MANIFEST, BUNDLE)}
    if actual != expected:
        raise ValueError('Release manifest differs from package bytes')
    bundle = Path(bundle) if bundle is not None else directory / BUNDLE
    if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size > 8*LIMIT:
        raise ValueError('Release attestation bundle missing or unsafe')
    verify_signature(manifest, bundle, value)
    return value


def attach(directory, channel):
    """Release writer revalidates regenerated bytes against the aggregate's proof."""
    bundle = Path('.work/attested-aggregate') / BUNDLE
    value = verify_local(directory, channel, bundle)
    with bundle.open('rb') as source, (Path(directory) / BUNDLE).open('xb') as target:
        shutil.copyfileobj(source, target)
    return value


def verify_remote(tag, assets, expected_identity=None, repo=REPOSITORY):
    import tempfile
    if repo != REPOSITORY:
        raise ValueError('Unexpected release attestation repository')
    names = [a.get('name') for a in assets]
    if len(names) != len(set(names)) or not {MANIFEST, BUNDLE}.issubset(names) or 'SHA256SUMS' in names:
        raise ValueError('Release requires attestation JSON and update manifest, without SHA256SUMS')
    for a in assets:
        if (a.get('state') != 'uploaded' or type(a.get('size')) is not int or a['size'] <= 0
                or not re.fullmatch('sha256:[0-9a-f]{64}', a.get('digest', ''))):
            raise ValueError('Release asset lacks size/digest or is incomplete')
    with tempfile.TemporaryDirectory(prefix='release-attestation-') as temp:
        root = Path(temp)
        for name in (MANIFEST, BUNDLE):
            a = next(a for a in assets if a['name'] == name)
            limit = LIMIT if name == MANIFEST else 8*LIMIT
            if type(a.get('id')) is not int or a['id'] <= 0 or a['size'] > limit:
                raise ValueError('Release JSON requires a verified GitHub asset ID and bounded size')
            target = root / name
            with target.open('wb') as stream:
                subprocess.run(['gh', 'api', f'repos/{repo}/releases/assets/{a["id"]}',
                                '--header', 'Accept: application/octet-stream'],
                               check=True, stdout=stream, stderr=subprocess.PIPE, timeout=120)
            if target.stat().st_size != a['size'] or sha(target) != a['digest'][7:]:
                raise ValueError('Remote release JSON does not match GitHub size/digest')
        value = loads((root / MANIFEST).read_bytes())
        if value['channel'] != 'stable' or tag != 'v'+value['upstream_version']+'-custom.'+value.get('patch_revision', ''):
            raise ValueError('Release manifest tag/channel mismatch')
        for key, expected_value in (expected_identity or {}).items():
            if value.get(key) != expected_value:
                raise ValueError('Remote release attestation identity mismatch: '+key)
        expected = {a['name']: (a['size'], a['sha256']) for a in value['assets']}
        actual = {a['name']: (a['size'], a['digest'][7:]) for a in assets if a['name'] not in (MANIFEST, BUNDLE)}
        if actual != expected:
            raise ValueError('Release asset digests do not match its attested manifest')
        verify_signature(root / MANIFEST, root / BUNDLE, value)
    return True
