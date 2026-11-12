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
SCHEMA = 'rustdesk-release-manifest-v2'
PREDICATE = 'https://slsa.dev/provenance/v1'
REPOSITORY = 'billradar/rustdesk-custom'
REPOSITORY_ID = '1399548376'
OWNER_ID = '56966687'
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
    if value.get('repository_id')!=REPOSITORY_ID or value.get('repository_owner_id')!=OWNER_ID:
        raise ValueError('Release numeric repository/owner identity mismatch')
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
    if value.get('version_semantics') != 'patchset-content-v1' or value.get('upstream_repository') != 'rustdesk/rustdesk':
        raise ValueError('Unknown release version/source semantics')
    content_version=value.get('patchset_version','')
    if not re.fullmatch(re.escape(value['patchset'])+r'\.[1-9][0-9]{0,5}',str(content_version)):
        raise ValueError('Invalid manifest content version')
    if value['channel']=='stable' and (content_version!=revision or value.get('upstream_tag') not in (value['upstream_version'],'v'+value['upstream_version'])):
        raise ValueError('Stable manifest tag/content version mismatch')
    if value['channel']=='nightly' and value.get('upstream_tag') is not None:
        raise ValueError('Nightly manifest cannot claim a Stable tag')
    for flag in ('wayland_included','android_signing_enabled','android_production_signed'):
        if type(value.get(flag)) is not bool:raise ValueError('Invalid manifest option: '+flag)
    policy=value.get('wayland_policy_sha256','')
    if (value['wayland_included'] and not re.fullmatch('[0-9a-f]{64}',str(policy))) or (not value['wayland_included'] and policy!=''):
        raise ValueError('Manifest Wayland policy mismatch')
    if not re.fullmatch(r'[1-9][0-9]*',str(value.get('prepare_run',''))):
        raise ValueError('Invalid manifest source preparation run')
    if value.get('prepare_run')!=value['build_run']:
        raise ValueError('Manifest preparation/build run mismatch')
    if value['channel']=='nightly':
        run=value.get('official_run_id')
        if not re.fullmatch(r'[1-9][0-9]*',str(run)) or value.get('official_run_url')!='https://github.com/rustdesk/rustdesk/actions/runs/'+str(run):
            raise ValueError('Invalid official Nightly run provenance')
    elif value.get('official_run_id') is not None or value.get('official_run_url') is not None:
        raise ValueError('Stable manifest cannot claim a Nightly run')
    if value.get('build_identity')!=build_identity(value):
        raise ValueError('Manifest build identity mismatch')
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
        if asset.get('signing_status') not in ('NOT ENABLED','TEST SIGNED / NOT PRODUCTION SIGNED','PRODUCTION SIGNED / IDENTITY VERIFIED'):
            raise ValueError('Unknown manifest package signing state')
        selector = (platform, arch, variant, flavor, package)
        if name in names or selector in selectors:
            raise ValueError('Duplicate release manifest name/selector')
        names.add(name); selectors.add(selector)
    flavors=[a for a in assets if a['flavor']=='unattended-wayland']
    if value['wayland_included'] != bool(flavors):
        raise ValueError('Manifest Wayland option/inventory mismatch')
    android=[a for a in assets if a['os']=='android']
    signed=len(android)==3 and all(a.get('signing_status')=='PRODUCTION SIGNED / IDENTITY VERIFIED' for a in android)
    if value['android_production_signed'] != signed:
        raise ValueError('Manifest Android signing inventory mismatch')
    return value


def require_production_signing(value, *, enforce_current=True):
    """Publication/reuse gate; build-only dry-run inventories remain representable."""
    if (value['android_signing_enabled'] or (enforce_current and os.environ.get('REQUIRE_ANDROID_PRODUCTION_SIGNING')=='true')) and not value['android_production_signed']:
        raise ValueError('Manifest requires three production-signed Android packages')


def build_identity(value):
    if value['channel']=='stable':
        from scripts.release.channel import build_identity as stable_identity
        return stable_identity(value['upstream_sha'],value['patchset'],value['common_patch_hash'],value['sos_patch_hash'],
                               wayland_included=value['wayland_included'],wayland_policy_sha256=value['wayland_policy_sha256'],
                               android_signing_enabled=value['android_signing_enabled'])
    from scripts.release.coordinator_lite import from_hashes
    return from_hashes(value['upstream_sha'],value['common_patch_hash'],value['sos_patch_hash'])


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
    from scripts.upstream.patchset_version import current
    value.update(repository_id=os.environ.get('GITHUB_REPOSITORY_ID',REPOSITORY_ID),repository_owner_id=os.environ.get('GITHUB_REPOSITORY_OWNER_ID',OWNER_ID),version_semantics='patchset-content-v1',patchset_version=info.get('patch_revision') if channel=='stable' else f'{info["patchset"]}.{current(info["patchset"])["revision"]}',
                 upstream_repository='rustdesk/rustdesk',upstream_tag=(info.get('upstream_tag') or info['upstream_version']) if channel=='stable' else None,
                 wayland_included=bool(report.get('wayland')),wayland_policy_sha256=report.get('wayland',{}).get('policy_sha256',''),
                 android_signing_enabled=os.environ.get('ANDROID_PRODUCTION_SIGNING_ENABLED','false')=='true',
                 android_production_signed=len([a for a in entries if a['os']=='android'])==3 and all(a.get('signing_status')=='PRODUCTION SIGNED / IDENTITY VERIFIED' for a in entries if a['os']=='android'),
                 prepare_run=str(info.get('prepare_run',os.environ['GITHUB_RUN_ID'])),
                 official_run_id=str(report['official_run_id']) if channel=='nightly' else None,
                 official_run_url=report['official_run_url'] if channel=='nightly' else None)
    value['build_identity']=build_identity(value)
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
    result=subprocess.run(['gh','attestation','verify',str(manifest),'--bundle',str(bundle),
                    '--repo',REPOSITORY,'--signer-workflow',REPOSITORY+'/.github/workflows/'+workflow,
                    '--source-ref','refs/heads/main','--source-digest',value['custom_repository_sha'],
                    '--predicate-type',PREDICATE,'--deny-self-hosted-runners','--format','json'],
                   check=True,capture_output=True,text=True,timeout=120)
    validate_verification_result(json.loads(result.stdout),value)


def validate_verification_result(result,value):
    if not isinstance(result,list) or len(result)!=1:
        raise ValueError('Expected exactly one verified attestation')
    verified=result[0].get('verificationResult',{})
    cert=verified.get('signature',{}).get('certificate',{})
    workflow='tag.yml' if value['channel']=='stable' else 'nightly.yml'
    identity=f'https://github.com/{REPOSITORY}/.github/workflows/{workflow}@refs/heads/main'
    expected={'issuer':'https://token.actions.githubusercontent.com','subjectAlternativeName':identity,
              'buildSignerURI':identity,'buildSignerDigest':value['custom_repository_sha'],
              'runnerEnvironment':'github-hosted','sourceRepositoryURI':'https://github.com/'+REPOSITORY,
              'sourceRepositoryDigest':value['custom_repository_sha'],'sourceRepositoryRef':'refs/heads/main',
              'sourceRepositoryIdentifier':value['repository_id'],'sourceRepositoryOwnerIdentifier':value['repository_owner_id'],
              'buildConfigURI':identity,'buildConfigDigest':value['custom_repository_sha'],'buildTrigger':'workflow_dispatch'}
    if any(cert.get(k)!=v for k,v in expected.items()):
        raise ValueError('Attestation certificate repository/workflow/source identity mismatch')
    invocation=cert.get('runInvocationURI','')
    if not re.fullmatch(re.escape(f'https://github.com/{REPOSITORY}/actions/runs/{value["build_run"]}/attempts/')+r'[1-9][0-9]*',invocation):
        raise ValueError('Attestation certificate run mismatch')
    statement=verified.get('statement',{})
    if statement.get('_type')!='https://in-toto.io/Statement/v1' or statement.get('predicateType')!=PREDICATE:
        raise ValueError('Unknown verified attestation statement')
    details=statement.get('predicate',{}).get('runDetails',{})
    if details.get('builder',{}).get('id')!=identity or details.get('metadata',{}).get('invocationId')!=invocation:
        raise ValueError('Provenance builder/run differs from certificate')


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
    require_production_signing(value)
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


def read_remote(tag, assets, expected_identity=None, repo=REPOSITORY, channel="stable", *, enforce_current_signing=True):
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
        require_production_signing(value,enforce_current=enforce_current_signing)
        expected_tag='nightly' if channel=='nightly' else 'v'+value['upstream_version']+'-custom.'+value.get('patch_revision', '')
        if value['channel'] != channel or tag != expected_tag:
            raise ValueError('Release manifest tag/channel mismatch')
        for key, expected_value in (expected_identity or {}).items():
            if value.get(key) != expected_value:
                raise ValueError('Remote release attestation identity mismatch: '+key)
        expected = {a['name']: (a['size'], a['sha256']) for a in value['assets']}
        actual = {a['name']: (a['size'], a['digest'][7:]) for a in assets if a['name'] not in (MANIFEST, BUNDLE)}
        if actual != expected:
            raise ValueError('Release asset digests do not match its attested manifest')
        verify_signature(root / MANIFEST, root / BUNDLE, value)
    return value


def verify_remote(tag, assets, expected_identity=None, repo=REPOSITORY):
    read_remote(tag,assets,expected_identity,repo)
    return True


def read_release(release, channel='stable', expected_identity=None, tag=None, *, enforce_current_signing=True):
    if (type(release.get('id')) is not int or release['id']<=0
            or type(release.get('draft')) is not bool
            or release.get('prerelease') is not (channel=='nightly')):
        raise ValueError('Invalid Release API identity/state')
    canonical=tag or release.get('tag_name','')
    value=read_remote(canonical,release.get('assets',[]),expected_identity,channel=channel,enforce_current_signing=enforce_current_signing)
    if release.get('target_commitish')!=value['custom_repository_sha']:
        raise ValueError('Release target commit differs from attested source')
    return value
