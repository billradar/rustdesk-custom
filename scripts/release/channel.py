#!/usr/bin/env python3
"""Channel identity and paired validation; stable publication is draft-only."""
import argparse, hashlib, json, os, re, subprocess, tempfile
from pathlib import Path
from scripts.upstream.resolve import api, choose_stable, resolve_ref
from scripts.release.github import collect, request, gh
from scripts.upstream.patchsets import verify, patch_hash, require_selection
from scripts.upstream.patchset_version import current, SCHEMA as VERSION_SEMANTICS
from scripts.release.production import assets, REPOSITORY
from scripts.release.naming import windows_installer_name
ROOT=Path(__file__).resolve().parents[2]

def outputs(data):
    Path('.work').mkdir(exist_ok=True)
    Path('.work/channel.json').write_text(json.dumps(data,indent=2)+'\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            for k,v in data.items():
                s=str(v).lower() if isinstance(v,bool) else str(v)
                if '\n' in s or '\r' in s:raise ValueError('Unsafe channel output')
                f.write(f'{k}={s}\n')
    print(json.dumps(data,indent=2))

def build_identity(upstream_sha, patchset, common_hash, sos_hash, custom_sha=None,
                   wayland_included=None, wayland_policy_sha256='', android_signing_enabled=False):
    if not isinstance(wayland_included, bool):
        raise ValueError('Stable identity requires an explicit Wayland selection')
    if wayland_included and not re.fullmatch(r'[0-9a-f]{64}', wayland_policy_sha256):
        raise ValueError('Stable Wayland identity requires the policy SHA-256')
    if not wayland_included and wayland_policy_sha256:
        raise ValueError('Wayland policy hash supplied while Wayland is disabled')
    identity = dict(schema='stable-build-identity-v4', upstream_sha=upstream_sha,
                    patchset=patchset, common_patch_hash=common_hash, sos_patch_hash=sos_hash,
                    wayland_included=wayland_included,
                    wayland_policy_sha256=wayland_policy_sha256,
                    android_signing_enabled=bool(android_signing_enabled))
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def legacy_build_identity(upstream_sha, patchset, common_hash, sos_hash, custom_sha,
                          wayland_included, wayland_policy_sha256, android_signing_enabled):
    """Reconstruct v3 identities so complete releases remain reusable after migration."""
    identity = dict(schema='stable-build-identity-v3', upstream_sha=upstream_sha,
                    patchset=patchset, common_patch_hash=common_hash, sos_patch_hash=sos_hash,
                    custom_repository_sha=custom_sha, wayland_included=wayland_included,
                    wayland_policy_sha256=wayland_policy_sha256,
                    android_signing_enabled=bool(android_signing_enabled))
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def wayland_identity():
    included = os.environ.get('INCLUDE_WAYLAND', 'false').lower() == 'true'
    if not included:
        return False, ''
    from scripts.platform.wayland import POLICY
    return True, hashlib.sha256(POLICY.read_bytes()).hexdigest()


def verify_release_asset_attestation(tag, assets, expected_identity=None):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-custom\.v[1-9][0-9]*\.[1-9][0-9]{0,5}',tag):
        raise ValueError('Invalid Stable release tag for asset verification')
    from scripts.release.attestation import verify_remote
    return verify_remote(tag, assets, expected_identity)

PATCHSET_RE = re.compile(r'^v([1-9][0-9]*)$')
CUSTOM_REVISION_RE = re.compile(r'^v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-custom\.v(?P<patch>[1-9][0-9]*)\.(?P<revision>[1-9][0-9]{0,5})$')

def release_rows(version):
    rows=[]
    for page in range(1,101):
        batch=api(f'repos/{REPOSITORY}/releases?per_page=100&page={page}') or []
        rows += batch
        if len(batch)<100: break
    return rows

def release_tag_name(row, version):
    for value in (row.get('tag_name'), row.get('name')):
        if value and CUSTOM_REVISION_RE.fullmatch(value) and value.startswith(f'v{version}-custom.'):
            return value
    return None

def require_release_tag(row, version):
    tag=release_tag_name(row,version)
    if not tag: raise ValueError('Existing Build Identity has invalid revision tag')
    return tag

def next_patch_revision(version, patchset):
    """Current Patchset content revision; never allocate from GitHub Releases."""
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Invalid Stable upstream version')
    require_selection(version, patchset, channel='stable')
    if not PATCHSET_RE.fullmatch(patchset):
        raise ValueError('Invalid Patchset version namespace')
    try:
        data = current(patchset)
    except OSError as error:
        raise ValueError('Reviewed Patchset content manifest unavailable') from error
    if data.get('id') != patchset or type(data.get('revision')) is not int:
        raise ValueError('Patchset content revision mismatch')
    return f'{patchset}.{data["revision"]}'


def parse_patch_revision(tag, version):
    match=CUSTOM_REVISION_RE.fullmatch(tag)
    if not match or match.group('version') != version:
        raise ValueError('Invalid custom patch revision')
    return f'v{match.group("patch")}.{match.group("revision")}'

def matching_drafts(tag):
    drafts=[]
    for page in range(1,101):
        rows=api(f'repos/{REPOSITORY}/releases?per_page=100&page={page}') or []
        drafts += [r for r in rows if r.get('draft') and r.get('name')==tag]
        if len(rows)<100:return drafts
    raise ValueError('Release pagination exhausted; manual review required')

def release_preflight(data, *, dry_run=False):
    if type(dry_run) is not bool:
        raise ValueError('Invalid Stable dry-run preflight override')
    if data.get("channel")!="stable": raise ValueError("Release preflight requires stable discovery")
    if not re.fullmatch(r"[0-9a-f]{40}",data.get("upstream_sha","")): raise ValueError("Invalid locked upstream SHA")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+",data.get("version","")): raise ValueError("Invalid stable version")
    if not PATCHSET_RE.fullmatch(data.get("patchset","")): raise ValueError("Invalid patchset")
    if data.get('upstream_ref')!=data.get('upstream_tag') or data.get('upstream_tag') not in (data['version'],'v'+data['version']):
        raise ValueError('Locked stable ref mismatch')
    require_selection(data['version'], data['patchset'], channel='stable')
    custom_sha=os.environ.get('GITHUB_SHA','')
    if not re.fullmatch(r'[0-9a-f]{40}',custom_sha): raise ValueError('Stable preflight requires the exact custom repository SHA')
    wayland_included,wayland_policy_sha256=wayland_identity()
    data.update(custom_repository_sha=custom_sha,wayland_included=wayland_included,
                wayland_policy_sha256=wayland_policy_sha256)
    common_hash=patch_hash('common',data['patchset'])
    sos_hash=patch_hash('sos',data['patchset'])
    signing_enabled=os.environ.get('ANDROID_PRODUCTION_SIGNING_ENABLED','false').lower()=='true'
    current_identity=build_identity(data['upstream_sha'],data['patchset'],common_hash,
                                    sos_hash,None,wayland_included,wayland_policy_sha256,
                                    signing_enabled)
    # Immutable tag is the reviewed Patchset content revision, not an
    # incrementing Release count. Historical tags retain original semantics.
    revision = next_patch_revision(data['version'], data['patchset'])
    if 'patch_revision' in data and data['patch_revision'] != revision:
        raise ValueError('Locked Patchset content revision drift')
    data['patch_revision'] = data['revision'] = data['patchset_version'] = revision
    data['version_semantics'] = VERSION_SEMANTICS
    data['release_tag'] = f'v{data["version"]}-custom.{revision}'
    accepted_build_identity = current_identity
    if dry_run:
        # Keep all locked input and Patchset checks, but never inspect/reuse a
        # Release or suppress a validation build merely because a Draft exists.
        data.update(build_needed=True, draft_needed=False, publish_existing=False,
                    build_identity=current_identity, rebuild_reason='DRY_RUN_VALIDATION_ONLY')
        return data
    existing=api(f'repos/{REPOSITORY}/releases/tags/{data["release_tag"]}',missing=True)
    if not existing:
        drafts=matching_drafts(data['release_tag'])
        if len(drafts)>1: raise ValueError('Duplicate revision drafts; manual review required')
        existing=drafts[0] if drafts else None
    if not existing:
        if api(f'repos/{REPOSITORY}/git/ref/tags/{data["release_tag"]}',missing=True): raise ValueError('Existing tag without completed release; review revision')
        data['build_needed']=True;data['draft_needed']=True;data['publish_existing']=False;data['build_identity']=current_identity;data['rebuild_reason']='NEW_CONTENT_VERSION_TARGET'
        return data
    if existing.get('prerelease') is not False:
        raise ValueError('Existing release is not Stable; never overwrite')
    from scripts.release.attestation import read_release
    expected=dict(upstream_version=data['version'],upstream_tag=data['upstream_tag'],upstream_sha=data['upstream_sha'],
                  patchset=data['patchset'],patchset_version=revision,patch_revision=revision,
                  common_patch_hash=common_hash,sos_patch_hash=sos_hash,wayland_included=wayland_included,
                  wayland_policy_sha256=wayland_policy_sha256,android_signing_enabled=signing_enabled,
                  build_identity=current_identity)
    value=read_release(existing,'stable',expected_identity=expected,tag=data['release_tag'])
    reference=api(f'repos/{REPOSITORY}/git/ref/tags/{data["release_tag"]}',missing=True)
    from scripts.release.stable_tag import commit_of
    if not reference or commit_of(REPOSITORY,reference)!=value['custom_repository_sha']:
        raise ValueError('Existing Stable tag differs from attested custom commit')
    if signing_enabled and not value['android_production_signed']:
        raise ValueError('Existing Stable release lacks required Android production signatures')
    data.update(build_needed=False,draft_needed=False,publish_existing=existing['draft'],
                build_identity=current_identity,custom_repository_sha=value['custom_repository_sha'])
    return data

def resolve(channel,ref='',discovery_only=False):
    if channel not in ('ci','stable'):
        raise ValueError('Unsupported channel here; use the verified official-run Nightly resolver')
    if channel=='stable':
        data=choose_stable(ref)
        data['upstream_ref']=data['upstream_tag']
    else:
        repo=api('repos/rustdesk/rustdesk');branch=repo['default_branch']
        chosen=ref or branch
        data={'upstream_sha':resolve_ref(chosen),'upstream_branch':chosen,'upstream_ref':chosen,
              'upstream_tag':'','build_needed':True,'draft_needed':False}
    data['channel']=channel;outputs(data)

def validate_prepared(infos,folders):
    for variant,info in infos.items():
        manifest=json.loads((folders[variant]/'source-manifest.json').read_text())
        for key in ('upstream_sha','patchset','common_patch_hash','sos_patch_hash','custom_repository_sha','variant','upstream_version'):
            if manifest[key]!=info[key]:raise ValueError('Source/build provenance mismatch: '+key)
        if hashlib.sha256((folders[variant]/'source-manifest.json').read_bytes()).hexdigest()!=info['prepared_source_manifest_hash']:
            raise ValueError('Source manifest hash mismatch')
        if str(info['prepare_run'])!=os.environ['GITHUB_RUN_ID'] or str(info['build_run'])!=os.environ['GITHUB_RUN_ID']:
            raise ValueError('Source/build run mismatch')
    for k in ('channel','upstream_version','prepare_run','build_adapter_signature'):
        if infos['standard'][k]!=infos['sos'][k]:raise ValueError('Pair identity mismatch: '+k)

def validate(root,channel):
    infos,folders=collect(root);validate_prepared(infos,folders)
    if any(i['channel']!=channel for i in infos.values()):raise ValueError('Channel mismatch')
    if channel=='stable':assets(root)
    else:
        from scripts.signing.production_config import payload
        from scripts.release.production import scan_job_log
        for folder in folders.values():payload(folder)
        # Captured logs only, no credentials printed.
        for job in api(f'repos/{REPOSITORY}/actions/runs/{os.environ["GITHUB_RUN_ID"]}/jobs?per_page=100')['jobs']:
            if job['status']=='completed' and job['conclusion']=='success':scan_job_log(job['id'])
    report={'result':'PASS','channel':channel,'upstream_sha':infos['standard']['upstream_sha'],
            'patchset':infos['standard']['patchset'],'common_patch_hash':infos['standard']['common_patch_hash'],
            'sos_patch_hash':infos['sos']['sos_patch_hash'],'runtime_ui':'SKIPPED BY USER',
            'real_remote_session':'NOT TESTED','signing':'NOT ENABLED','credential_scan':'KNOWN PATTERNS ONLY'}
    baseline=json.loads((ROOT/'metadata/baselines/source-regression.json').read_text())
    if infos['standard']['upstream_sha']==baseline['upstream_sha']:
        comparisons={k: infos['standard'].get(k)==baseline[k] for k in ('upstream_sha','patchset','common_patch_hash','server_config_fingerprint')}
        comparisons['sos_patch_hash']=infos['sos']['sos_patch_hash']==baseline['sos_patch_hash']
        if not all(comparisons.values()):raise ValueError('Source regression baseline identity mismatch')
        report['Source regression baseline comparison']=comparisons
    else:report['Source regression baseline comparison']='NOT APPLICABLE: different upstream SHA'
    Path('.work/channel-validation.json').write_text(json.dumps(report,indent=2)+'\n')

def draft(root):
    if os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY:raise ValueError('Wrong release repository')
    # Revalidate the downloaded pair in the write-permission job before any write.
    infos,folders=collect(root);validate_prepared(infos,folders)
    if any(i['channel']!='stable' for i in infos.values()):raise ValueError('Only stable creates drafts')
    _,directory=assets(root)
    info=infos['standard']
    expected_version=next_patch_revision(info['upstream_version'], info['patchset'])
    if info['patch_revision'] != expected_version:
        raise ValueError('Artifact Patchset content revision changed before draft')
    tag=f'v{info["upstream_tag"].lstrip("v")}-custom.{expected_version}'
    if api(f'repos/{REPOSITORY}/releases/tags/{tag}',missing=True) or api(f'repos/{REPOSITORY}/git/ref/tags/{tag}',missing=True):raise ValueError('No overwrite')
    if any(r.get('draft') and r.get('name')==tag for r in (api(f'repos/{REPOSITORY}/releases?per_page=100') or [])):
        raise ValueError('Existing unpublished revision draft; never replace it')
    changelog=(info.get('upstream_changelog') or '').strip()
    if not changelog:
        upstream_release=api(f'repos/rustdesk/rustdesk/releases/tags/{info["upstream_tag"]}',missing=True)
        changelog=((upstream_release or {}).get('body') or '').strip()
    if not changelog:raise ValueError('Official upstream release changelog is empty')
    wayland_included,wayland_policy_sha256=wayland_identity()
    from scripts.release.content import notes as patchset_notes
    from scripts.release.attestation import attach
    attach(directory,'stable')
    release_files=sorted(directory.iterdir())
    notes=changelog+'\n\n'+patchset_notes(info['patchset'])
    result=request('POST',f'repos/{REPOSITORY}/releases',{'tag_name':tag,'target_commitish':info['custom_repository_sha'],
                    'name':tag,'body':notes,'draft':True,'prerelease':False})
    gh('release','upload',tag,*map(str,release_files),'--repo',REPOSITORY)
    uploaded=api(f'repos/{REPOSITORY}/releases/{result["id"]}/assets')
    expected={p.name:p.stat().st_size for p in release_files}
    if {a['name']:a['size'] for a in uploaded if a['state']=='uploaded'}!=expected:
        raise ValueError('Incomplete draft upload; remains unpublished')
    from scripts.release.stable_tag import ensure
    ensure(REPOSITORY,tag,info['custom_repository_sha'])
    # GitHub can keep an untagged-* Draft URL even when its API tag_name and
    # the backing immutable Git ref are both canonical. Never publish to fix UI.
    final=request('PATCH',f'repos/{REPOSITORY}/releases/{result["id"]}',
                  {'tag_name':tag,'target_commitish':info['custom_repository_sha'],
                   'draft':True,'prerelease':False,'body':notes})
    if (final.get('draft') is not True or final.get('prerelease') is not False
            or final.get('tag_name') != tag):
        raise ValueError('Stable Draft state or tag association mismatch')
    print('Draft created with verified immutable Git tag; publication disabled.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['resolve','release-preflight','validate','draft']);p.add_argument('--channel',choices=['ci','stable','nightly'],default='ci');p.add_argument('--ref',default='');p.add_argument('--discovery-only',action='store_true');p.add_argument('--discovery',type=Path);p.add_argument('--patchset',default='');p.add_argument('--root',type=Path,default=Path('.work/collected'));a=p.parse_args()
    if a.mode=='resolve':resolve(a.channel,a.ref,a.discovery_only)
    elif a.mode=='release-preflight':
        data=json.loads(a.discovery.read_text());data['patchset']=a.patchset or data.get('patchset','');result=release_preflight(data)
        outputs(result)
    elif a.mode=='validate':validate(a.root,a.channel)
    else:draft(a.root)
