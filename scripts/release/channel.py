#!/usr/bin/env python3
"""Channel identity and paired validation; stable publication is draft-only."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from scripts.upstream.resolve import api, choose_stable, resolve_ref
from scripts.release.github import collect, request, gh
from scripts.upstream.patchsets import verify, patch_hash
from scripts.release.production import assets, REPOSITORY
ROOT=Path(__file__).resolve().parents[1]

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

def matching_drafts(tag):
    drafts=[]
    for page in range(1,101):
        rows=api(f'repos/{REPOSITORY}/releases?per_page=100&page={page}') or []
        drafts += [r for r in rows if r.get('draft') and r.get('name')==tag]
        if len(rows)<100:return drafts
    raise ValueError('Release pagination exhausted; manual review required')

def release_preflight(data,force=False):
    if data.get("channel")!="stable":raise ValueError("Release preflight requires stable discovery")
    if not re.fullmatch(r"[0-9a-f]{40}",data.get("upstream_sha","")):raise ValueError("Invalid locked upstream SHA")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+",data.get("version","")):raise ValueError("Invalid stable version")
    if not re.fullmatch(r"[1-9][0-9]{0,5}",data.get("revision","")):raise ValueError("Invalid revision")
    if data.get("release_tag")!=f'v{data["version"]}-custom.{data["revision"]}':raise ValueError("Release identity mismatch")
    if data.get('upstream_ref')!=data.get('upstream_tag') or data.get('upstream_tag') not in (data['version'],'v'+data['version']):
        raise ValueError('Locked stable ref mismatch')
    existing=api(f'repos/{REPOSITORY}/releases/tags/{data["release_tag"]}',missing=True)
    if not existing:
        # GitHub may expose an unpublished draft under a temporary untagged ID.
        drafts=matching_drafts(data['release_tag'])
        if len(drafts)>1:raise ValueError('Duplicate revision drafts; manual review required')
        existing=drafts[0] if drafts else None
    if existing:
        body=existing.get('body') or ''
        generation=re.search(r'^Patch Set: (v[1-9][0-9]*)$',body,re.M)
        if generation is None:raise ValueError('Existing release missing generation identity')
        name=generation.group(1);verify(name)
        expected=[f'Upstream SHA: {data["upstream_sha"]}',f'Common Patch Hash: {patch_hash("common",name)}',
                  f'SOS Patch Hash: {patch_hash("sos",name)}','Automation-State: complete']
        required={'SHA256SUMS','build-info-standard.json','build-info-sos.json',
                  f'rustdesk-{data["version"]}-standard-windows-x86_64.zip',f'rustdesk-{data["version"]}-sos-windows-x86_64.zip'}
        inventory=re.search(r'^Asset Inventory: (\[.*\])$',body,re.M)
        if inventory:
            supplied=json.loads(inventory.group(1))
            if not required.issubset(set(supplied)) or len(set(supplied))!=len(supplied):raise ValueError('Invalid historical asset inventory')
            required=set(supplied)
        if existing['prerelease'] or not all(x in body for x in expected) or {x['name'] for x in existing['assets'] if x['state']=='uploaded'}!=required:
            raise ValueError('Existing release incomplete or incompatible; never overwrite')
        data['build_needed']=force;data['draft_needed']=False
    else:
        if api(f'repos/{REPOSITORY}/git/ref/tags/{data["release_tag"]}',missing=True):raise ValueError('Existing tag without completed release; review revision')
        data['build_needed']=True;data['draft_needed']=True
    return data

def resolve(channel,ref='',force=False,discovery_only=False):
    if channel=='stable':
        data=choose_stable(ref)
        revision=(ROOT/'patch-revision.txt').read_text().strip()
        if not re.fullmatch('[1-9][0-9]{0,5}',revision):raise ValueError('Invalid revision')
        data['revision']=revision;data['release_tag']=f'v{data["version"]}-custom.{revision}'
        data['upstream_ref']=data['upstream_tag']
        if not discovery_only:
            data['channel']='stable'
            release_preflight(data,force)
    else:
        repo=api('repos/rustdesk/rustdesk');branch=repo['default_branch']
        chosen=ref or branch
        data={'upstream_sha':resolve_ref(chosen),'upstream_branch':chosen,'upstream_ref':chosen,
              'upstream_tag':'','build_needed':True,'draft_needed':False,'revision':(ROOT/'patch-revision.txt').read_text().strip()}
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
    baseline=json.loads((ROOT/'metadata/source-regression-baseline.json').read_text())
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
    notes='\n'.join([f'Upstream: rustdesk/rustdesk',f'Upstream Tag: {info["upstream_tag"]}',f'Upstream SHA: {info["upstream_sha"]}',
        f'Patch Set: {info["patchset"]}',f'Custom Repository SHA: {info["custom_repository_sha"]}',f'Common Patch Hash: {info["common_patch_hash"]}',
        f'SOS Patch Hash: {infos["sos"]["sos_patch_hash"]}',f'Prepared Source Run: {info["prepare_run"]}',f'Build Run: {info["build_run"]}',
        'Variants: Standard / SOS','Platform: Windows x86_64','Build / Checksums / Architecture / Provenance: PASS',
        'Runtime/UI Validation: SKIPPED BY USER','Real Remote Session Validation: NOT TESTED','Code Signing: NOT ENABLED',
        'Password Security V2: DEFERRED','Embedded client configuration/password can be extracted by client owners.',
        'Release policy: DRAFT ONLY; publication is a manual user decision.'])+'\n'
    result=request('POST',f'repos/{REPOSITORY}/releases',{'tag_name':tag,'target_commitish':info['custom_repository_sha'],
                    'name':tag,'body':notes,'draft':True,'prerelease':False})
    gh('release','upload',tag,*map(str,sorted(directory.iterdir())),'--repo',REPOSITORY)
    uploaded=api(f'repos/{REPOSITORY}/releases/{result["id"]}/assets')
    if {a['name']:a['size'] for a in uploaded if a['state']=='uploaded'}!={p.name:p.stat().st_size for p in directory.iterdir()}:
        raise ValueError('Incomplete draft upload; remains unpublished')
    final=request('PATCH',f'repos/{REPOSITORY}/releases/{result["id"]}',{'draft':True,'body':notes+'Automation-State: complete\n'})
    if not final['draft']:raise ValueError('Draft protection failed')
    print('Draft created; automatic publication disabled.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['resolve','release-preflight','validate','draft']);p.add_argument('--channel',choices=['ci','stable','nightly'],default='ci');p.add_argument('--ref',default='');p.add_argument('--force',action='store_true');p.add_argument('--discovery-only',action='store_true');p.add_argument('--discovery',type=Path);p.add_argument('--root',type=Path,default=Path('.work/collected'));a=p.parse_args()
    if a.mode=='resolve':resolve(a.channel,a.ref,a.force,a.discovery_only)
    elif a.mode=='release-preflight':outputs(release_preflight(json.loads(a.discovery.read_text()),a.force))
    elif a.mode=='validate':validate(a.root,a.channel)
    else:draft(a.root)
