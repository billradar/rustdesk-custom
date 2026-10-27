#!/usr/bin/env python3
"""Channel identity and paired validation; stable publication is draft-only."""
import argparse, hashlib, json, os, re, subprocess, tempfile
from pathlib import Path
from scripts.upstream.resolve import api, choose_stable, resolve_ref
from scripts.release.github import collect, request, gh
from scripts.upstream.patchsets import verify, patch_hash
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


def verify_release_asset_checksums(tag, assets):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-custom\.v[1-9][0-9]*\.[1-9][0-9]{0,5}',tag):
        raise ValueError('Invalid Stable release tag for asset verification')
    names=[asset.get('name','') for asset in assets]
    if len(names)!=len(set(names)) or 'SHA256SUMS' not in names:
        raise ValueError('Stable release asset inventory is duplicate or missing SHA256SUMS')
    expected={}
    for asset in assets:
        digest=asset.get('digest','')
        if asset.get('state')!='uploaded' or asset.get('size',0)<=0 or not re.fullmatch(r'sha256:[0-9a-f]{64}',digest):
            raise ValueError('Stable release asset is incomplete or lacks a GitHub SHA-256 digest')
        if asset['name']!='SHA256SUMS':expected[asset['name']]=digest.removeprefix('sha256:')
    with tempfile.TemporaryDirectory(prefix='stable-release-assets-') as temp:
        subprocess.run(['gh','release','download',tag,'--repo',REPOSITORY,'--pattern','SHA256SUMS','--dir',temp],
                       check=True,capture_output=True,text=True,env=os.environ)
        checksum=Path(temp)/'SHA256SUMS'
        if not checksum.is_file() or checksum.stat().st_size>1024*1024:
            raise ValueError('Stable release SHA256SUMS could not be safely downloaded')
        raw=checksum.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=next(a['digest'][7:] for a in assets if a['name']=='SHA256SUMS'):
            raise ValueError('Stable remote SHA256SUMS digest does not match the GitHub asset digest')
    actual={}
    for line in raw.decode('utf-8').splitlines():
        match=re.fullmatch(r'([0-9a-f]{64})  ([^/\\]+)',line)
        if not match or match.group(2) in actual:
            raise ValueError('Stable remote SHA256SUMS is malformed or contains duplicate assets')
        actual[match.group(2)]=match.group(1)
    if actual!=expected:
        raise ValueError('Stable release asset digests do not match its SHA256SUMS')
    return True

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
    match=PATCHSET_RE.fullmatch(patchset)
    if not match: raise ValueError('Invalid patchset revision')
    patch_number=match.group(1)
    pattern=re.compile(r'^v'+re.escape(version)+r'-custom\.v'+re.escape(patch_number)+r'\.([1-9][0-9]{0,5})$')
    nums=[int(m.group(1)) for row in release_rows(version) if (tag:=release_tag_name(row,version)) and (m:=pattern.fullmatch(tag))]
    return f'v{patch_number}.{max(nums or [0])+1}'

def parse_patch_revision(tag, version):
    match=CUSTOM_REVISION_RE.fullmatch(tag)
    if not match or match.group('version') != version:
        raise ValueError('Invalid custom patch revision')
    return f'v{match.group("patch")}.{match.group("revision")}'

def same_identity_release(version, identity):
    for row in release_rows(version):
        body=row.get('body') or ''
        match=re.search(r'^Build Identity: ([0-9a-f]{64})$',body,re.M) or re.search(r'^build_identity=([0-9a-f]{64})$',body,re.M)
        if match and match.group(1)==identity: return row
    return None


def same_legacy_identity_release(data, common_hash, sos_hash, wayland_included,
                                 wayland_policy_sha256, android_signing_enabled):
    """Find a complete v3 release whose only obsolete identity input was repo commit SHA."""
    expected = {
        'Upstream SHA': data['upstream_sha'],
        'Patch Set': data['patchset'],
        'Common Patch Hash': common_hash,
        'SOS Patch Hash': sos_hash,
        'Wayland Included': str(wayland_included).lower(),
    }
    if wayland_policy_sha256:
        expected['Wayland Policy SHA256'] = wayland_policy_sha256
    for row in release_rows(data['version']):
        body = row.get('body') or ''
        fields = dict(re.findall(r'^([^:\n]+): (.*)$', body, re.M))
        if any(fields.get(key) != value for key, value in expected.items()):
            continue
        custom_sha = fields.get('Custom Repository SHA', '')
        if not re.fullmatch(r'[0-9a-f]{40}', custom_sha):
            continue
        recorded = re.search(r'^Build Identity: ([0-9a-f]{64})$', body, re.M)
        expected_legacy = legacy_build_identity(data['upstream_sha'], data['patchset'], common_hash,
                                               sos_hash, custom_sha, wayland_included,
                                               wayland_policy_sha256, android_signing_enabled)
        if recorded and recorded.group(1) == expected_legacy:
            return row, expected_legacy
    return None, None

def matching_drafts(tag):
    drafts=[]
    for page in range(1,101):
        rows=api(f'repos/{REPOSITORY}/releases?per_page=100&page={page}') or []
        drafts += [r for r in rows if r.get('draft') and r.get('name')==tag]
        if len(rows)<100:return drafts
    raise ValueError('Release pagination exhausted; manual review required')

def release_preflight(data):
    if data.get("channel")!="stable": raise ValueError("Release preflight requires stable discovery")
    if not re.fullmatch(r"[0-9a-f]{40}",data.get("upstream_sha","")): raise ValueError("Invalid locked upstream SHA")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+",data.get("version","")): raise ValueError("Invalid stable version")
    if not PATCHSET_RE.fullmatch(data.get("patchset","")): raise ValueError("Invalid patchset")
    if data.get('upstream_ref')!=data.get('upstream_tag') or data.get('upstream_tag') not in (data['version'],'v'+data['version']):
        raise ValueError('Locked stable ref mismatch')
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
    same=same_identity_release(data['version'],current_identity)
    accepted_build_identity=current_identity
    if not same:
        same,legacy_identity=same_legacy_identity_release(data,common_hash,sos_hash,wayland_included,
                                                          wayland_policy_sha256,signing_enabled)
        if same:
            accepted_build_identity=legacy_identity
    if same:
        data['release_tag']=require_release_tag(same,data['version'])
        data['patch_revision']=parse_patch_revision(data['release_tag'],data['version'])
        data['revision']=data['patch_revision']
    else:
        data['patch_revision']=next_patch_revision(data['version'],data['patchset'])
        data['revision']=data['patch_revision']
        data['release_tag']=f'v{data["version"]}-custom.{data["patch_revision"]}'
    existing=api(f'repos/{REPOSITORY}/releases/tags/{data["release_tag"]}',missing=True)
    if not existing:
        drafts=matching_drafts(data['release_tag'])
        if len(drafts)>1: raise ValueError('Duplicate revision drafts; manual review required')
        existing=drafts[0] if drafts else None
    if not existing:
        if api(f'repos/{REPOSITORY}/git/ref/tags/{data["release_tag"]}',missing=True): raise ValueError('Existing tag without completed release; review revision')
        data['build_needed']=True;data['draft_needed']=True;data['publish_existing']=False;data['build_identity']=current_identity;data['rebuild_reason']='NEW_PATCH_REVISION'
        return data
    body=existing.get('body') or ''
    if wayland_included:
        from scripts.platform.wayland import POLICY
        expected_policy = wayland_policy_sha256
        required_wayland = {'unattended-wayland-rustdesk-unattended-wayland-' + data['version'] + '-' + arch + '.deb' for arch in ['x86_64', 'aarch64']}
        uploaded_wayland = {a['name'] for a in existing.get('assets', []) if a.get('state') == 'uploaded'}
        if (('wayland_policy_sha256=' + expected_policy not in body and 'Wayland Policy SHA256: ' + expected_policy not in body)
                or not required_wayland <= uploaded_wayland):
            raise ValueError('Existing immutable revision lacks matching Wayland evidence; disable include_wayland to reuse it or create a new patch identity')
    generation=re.search(r'^Patch Set: (v[1-9][0-9]*)$',body,re.M) or re.search(r'^patchset=(v[1-9][0-9]*)$',body,re.M)
    if generation is None: raise ValueError('Existing release missing generation identity')
    name=generation.group(1);verify(name)
    expected_identity=[(f'Upstream SHA: {data["upstream_sha"]}',f'upstream_sha={data["upstream_sha"]}'),
                       (f'Patch Set: {name}',f'patchset={name}'),
                       (f'Common Patch Hash: {patch_hash("common",name)}',f'common_patch_hash={patch_hash("common",name)}'),
                       (f'SOS Patch Hash: {patch_hash("sos",name)}',f'sos_patch_hash={patch_hash("sos",name)}'),
                       (f'Patch Revision: {data["patch_revision"]}',f'custom_release_revision={data["patch_revision"]}'),
                       (f'Wayland Included: {str(wayland_included).lower()}',f'wayland_included={str(wayland_included).lower()}')]
    if wayland_policy_sha256:
        expected_identity.append(('Wayland Policy SHA256: '+wayland_policy_sha256,'wayland_policy_sha256='+wayland_policy_sha256))
    automation_marker='Automation-State: complete'
    legacy_lines=[x.strip() for x in body.splitlines() if x.strip().startswith('Automation-State:')]
    metadata_lines=[x.strip() for x in body.splitlines() if x.strip().startswith('automation_state=')]
    if legacy_lines and legacy_lines != [automation_marker]: raise ValueError('Existing release incomplete or incompatible (invalid automation state)')
    if metadata_lines and metadata_lines not in (['automation_state=complete'],['automation_state=published']): raise ValueError('Existing release incomplete or incompatible (invalid automation state)')
    if legacy_lines and metadata_lines: raise ValueError('Existing release has duplicate automation state markers')
    if not legacy_lines and not metadata_lines: raise ValueError('Existing release missing its automation completion marker')
    required={'SHA256SUMS',windows_installer_name(data['version'],'standard','exe'),windows_installer_name(data['version'],'standard','msi'),windows_installer_name(data['version'],'sos','exe'),windows_installer_name(data['version'],'sos','msi')}
    legacy_required={'SHA256SUMS',f'rustdesk-{data["version"]}-standard-windows-x86_64.zip',f'rustdesk-{data["version"]}-sos-windows-x86_64.zip'}
    inventory=re.search(r'^Asset Inventory: (.+)$',body,re.M) or re.search(r'^asset_inventory=(.+)$',body,re.M)
    has_inventory=bool(inventory)
    if inventory:
        supplied=json.loads(inventory.group(1))
        if not required.issubset(set(supplied)) and not legacy_required.issubset(set(supplied)): raise ValueError('Invalid historical asset inventory')
        if len(set(supplied))!=len(supplied): raise ValueError('Invalid historical asset inventory')
        required=set(supplied)
    all_assets=existing.get('assets',[])
    uploaded={x['name'] for x in all_assets if x.get('state')=='uploaded'}
    metadata_lines_set=set(body.splitlines())
    missing_identity=[values for values in expected_identity if not any(value in metadata_lines_set for value in values)]
    recorded=re.search(r'^Build Identity: ([0-9a-f]{64})$',body,re.M) or re.search(r'^build_identity=([0-9a-f]{64})$',body,re.M)
    identity_ok=not missing_identity and recorded is not None and recorded.group(1)==accepted_build_identity
    if identity_ok and not has_inventory:
        raise ValueError('Existing Stable release missing its exact asset inventory')
    if has_inventory:
        assets_ok=(required==uploaded and len(all_assets)==len(uploaded)
                   and all(re.fullmatch(r'sha256:[0-9a-f]{64}',x.get('digest','')) and x.get('size',0)>0 for x in all_assets))
    else:
        assets_ok=required.issubset(uploaded) or legacy_required.issubset(uploaded)
    if existing.get('prerelease') or not assets_ok: raise ValueError('Existing release incomplete or incompatible; never overwrite')
    if identity_ok:
        verify_release_asset_checksums(data['release_tag'],all_assets)
        data['build_needed']=False;data['draft_needed']=False;data['publish_existing']=bool(existing.get('draft'));data['build_identity']=current_identity
        return data
    raise ValueError('Existing revision tag has a different Build Identity; immutable revision collision')

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
    info=infos['standard'];tag=f'v{info["upstream_tag"].lstrip("v")}-custom.{info["patch_revision"]}'
    if api(f'repos/{REPOSITORY}/releases/tags/{tag}',missing=True) or api(f'repos/{REPOSITORY}/git/ref/tags/{tag}',missing=True):raise ValueError('No overwrite')
    if any(r.get('draft') and r.get('name')==tag for r in (api(f'repos/{REPOSITORY}/releases?per_page=100') or [])):
        raise ValueError('Existing unpublished revision draft; never replace it')
    release_files=sorted(p for p in directory.iterdir() if p.suffix.lower() != '.json')
    inventory=json.dumps([p.name for p in release_files],separators=(', ',': '))
    changelog=(info.get('upstream_changelog') or '').strip()
    if not changelog:
        upstream_release=api(f'repos/rustdesk/rustdesk/releases/tags/{info["upstream_tag"]}',missing=True)
        changelog=((upstream_release or {}).get('body') or '').strip()
    if not changelog:raise ValueError('Official upstream release changelog is empty')
    wayland_included,wayland_policy_sha256=wayland_identity()
    metadata='\n'.join([
        '<!-- rustdesk-custom-release-metadata',
        f'Upstream SHA: {info["upstream_sha"]}',
        f'Patch Set: {info["patchset"]}',
        f'Common Patch Hash: {info["common_patch_hash"]}',
        f'SOS Patch Hash: {infos["sos"]["sos_patch_hash"]}',
        f'Custom Repository SHA: {info["custom_repository_sha"]}',
        f'Wayland Included: {str(wayland_included).lower()}',
        *(('Wayland Policy SHA256: '+wayland_policy_sha256,) if wayland_policy_sha256 else ()),
        f'Patch Revision: {info["patch_revision"]}',
        f'Build Identity: {build_identity(info["upstream_sha"],info["patchset"],info["common_patch_hash"],infos["sos"]["sos_patch_hash"],None,wayland_included,wayland_policy_sha256,os.environ.get("REQUIRE_ANDROID_PRODUCTION_SIGNING", "false").lower()=="true")}',
        f'Asset Inventory: {inventory}',
        'automation_state=complete',
        '-->'
    ])
    notes=changelog+'\n\n'+metadata+'\n'
    result=request('POST',f'repos/{REPOSITORY}/releases',{'tag_name':tag,'target_commitish':info['custom_repository_sha'],
                    'name':tag,'body':notes,'draft':True,'prerelease':False})
    gh('release','upload',tag,*map(str,release_files),'--repo',REPOSITORY)
    uploaded=api(f'repos/{REPOSITORY}/releases/{result["id"]}/assets')
    expected={p.name:p.stat().st_size for p in release_files}
    if {a['name']:a['size'] for a in uploaded if a['state']=='uploaded'}!=expected:
        raise ValueError('Incomplete draft upload; remains unpublished')
    final=request('PATCH',f'repos/{REPOSITORY}/releases/{result["id"]}',{'draft':True,'body':notes})
    print('Draft created; automatic publication disabled.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['resolve','release-preflight','validate','draft']);p.add_argument('--channel',choices=['ci','stable','nightly'],default='ci');p.add_argument('--ref',default='');p.add_argument('--discovery-only',action='store_true');p.add_argument('--discovery',type=Path);p.add_argument('--patchset',default='');p.add_argument('--root',type=Path,default=Path('.work/collected'));a=p.parse_args()
    if a.mode=='resolve':resolve(a.channel,a.ref,a.discovery_only)
    elif a.mode=='release-preflight':
        data=json.loads(a.discovery.read_text());data['patchset']=a.patchset or data.get('patchset','');outputs(release_preflight(data))
    elif a.mode=='validate':validate(a.root,a.channel)
    else:draft(a.root)
