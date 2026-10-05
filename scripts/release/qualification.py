#!/usr/bin/env python3
"""Explicit targets and cross-platform fan-in; support requires reviewed Actions evidence."""
import argparse, hashlib, json, os, re, shutil, time, zipfile
from pathlib import Path
from scripts.upstream.patchsets import patch_hash
ROOT=Path(__file__).resolve().parents[2]
FORBIDDEN={'android','ios','web'}
def target(e):return '-'.join((e['platform'],e['arch'],e['variant']))
def entries():
    rows=json.loads((ROOT/'metadata/platform-matrix.json').read_text())['entries'];seen=set()
    reviewed=json.loads((ROOT/'metadata/platform-adapter-profiles.json').read_text())['audited']
    for e in rows:
        name=target(e)
        if name in seen:raise ValueError('Duplicate matrix target')
        seen.add(name)
        if e['platform'] in FORBIDDEN and e['variant']!='standard':raise ValueError('Forbidden SOS target')
        if e['support_status']=='SUPPORTED' and not e.get('evidence_run'):raise ValueError('SUPPORTED without Actions evidence')
        if e.get('enabled') and not e.get('runner'):raise ValueError('Enabled target without runner')
        if e.get('enabled') and not any(p['platform']==e['platform'] and p['architecture']==e['arch'] and p['runner']==e['runner'] for p in reviewed):
            raise ValueError('Matrix runner/architecture not present in reviewed upstream definitions')
        if e['support_status'] not in ('SUPPORTED','EXPERIMENTAL','PLANNED','BLOCKED','UNSUPPORTED','DISABLED'):
            raise ValueError('Unknown support status')
        if e.get('required') and e['support_status']!='SUPPORTED':raise ValueError('Experimental target cannot be required')
        if e['support_status']=='SUPPORTED' and not e.get('required'):raise ValueError('Supported target must be required')
    return rows

def plan(channel,experimental=False):
    selected=[dict(e,id=target(e)) for e in entries() if e.get('enabled') and
              (e['support_status']=='SUPPORTED' or (experimental and e['support_status']=='EXPERIMENTAL'))]
    if not selected:raise ValueError('Empty supported matrix')
    for e in selected:e['required']=e['support_status']=='SUPPORTED'
    return {'channel':channel,'selected':selected,'include_experimental':experimental}

def identity(i):
    return (i['upstream_sha'],i['patchset'],i['common_patch_hash'],i['custom_repository_sha'],str(i['build_run']))

def aggregate(root,channel,experimental):
    from scripts.platform.platform_package import validate
    from scripts.release.github import validate as windows_validate
    from scripts.release.channel import validate_prepared
    p=plan(channel,experimental);expected={e['id']:e for e in p['selected']};found={};folders={};errors=[]
    diagnostics={}
    for path in root.rglob('diagnostic.json'):
        data=json.loads(path.read_text());diagnostics[data['target']]=data
    for path in root.rglob('build-info.json'):
        i=json.loads(path.read_text());platform=i['platform'].removesuffix('-x86_64');name=platform+'-'+i['architecture']+'-'+i['variant']
        if name not in expected:raise ValueError('PROVENANCE: unexpected artifact '+name)
        if name in found:raise ValueError('PROVENANCE: duplicate artifact '+name)
        if platform=='windows':
            windows_validate(path.parent)
        else:validate(path.parent)
        if i['channel']!=channel:raise ValueError('PROVENANCE: channel mismatch')
        if platform=='android' and channel in ('stable','nightly') and os.environ.get('REQUIRE_ANDROID_PRODUCTION_SIGNING')=='true' and i.get('signed_status')!='PRODUCTION SIGNED / IDENTITY VERIFIED':raise ValueError('SIGNING: Stable Android requires verified production identity')
        found[name]=i;folders[name]=path.parent
    windows={i['variant']:i for n,i in found.items() if n.startswith('windows-x86_64-')}
    if len(windows)==2:
        validate_prepared(windows,{v:folders['windows-x86_64-'+v] for v in windows})
    if found:
        first=next(iter(found.values()))
        for i in found.values():
            if identity(i)!=identity(first):raise ValueError('PROVENANCE: cross-platform source/generation mismatch')
            if i.get('server_config_fingerprint')!=first.get('server_config_fingerprint'):raise ValueError('PROVENANCE: configuration mismatch')
        for variant in ('standard','sos'):
            sources={i.get('prepared_source_identity',i.get('prepared_source_manifest_hash')) for i in found.values() if i['variant']==variant}
            if len(sources)>1 or None in sources:raise ValueError('PROVENANCE: prepared variant identity mismatch')
    results={}
    for name,e in expected.items():
        i=found.get(name)
        results[name]={'result':'PASS' if i else 'FAILED / MISSING ARTIFACT','required':e['required'],'support_status':e['support_status']}
        if not i:
            results[name]['failure_category']=diagnostics.get(name,{}).get('failure_category','INFRASTRUCTURE')
            results[name]['failed_step']=diagnostics.get(name,{}).get('failed_step','NO VALIDATED ARTIFACT')
        if not i and e['required']:errors.append('Required target missing: '+name)
        if e['variant']=='sos' and i:
            pair=e['platform']+'-'+e['arch']+'-standard'
            if pair not in found:
                results[name]['result']='FAIL: Standard pair missing'
                errors.append('SOS source pairing missing: '+name)
    required_pass=not errors
    report={'result':'PASS' if required_pass and len(found)==len(expected) else 'PARTIAL' if required_pass else 'FAIL',
            'required_gate':'PASS' if required_pass else 'FAIL','targets':results,'errors':errors,
            'channel':channel,'upstream_sha':os.environ['UPSTREAM_EXPECTED_SHA'],'patchset':os.environ['PATCHSET'],
            'build_run':os.environ['GITHUB_RUN_ID'],'custom_repository_sha':os.environ['GITHUB_SHA'],
            'runtime_ui':'SKIPPED BY USER','real_remote_session':'NOT TESTED','code_signing':'DESKTOP NOT ENABLED; ANDROID '+('PRODUCTION IDENTITY VERIFIED' if all(i.get('signing_identity_verified') for i in found.values() if i['platform']=='android') and any(i['platform']=='android' for i in found.values()) else 'TEST ONLY')}
    out=ROOT/'.work/qualification-aggregate';out.mkdir(parents=True,exist_ok=True)
    (out/'aggregate.json').write_text(json.dumps(report,indent=2)+'\n')
    rows=[]
    for name,folder in folders.items():
        for file in sorted(folder.rglob('*')):
            if file.is_file():rows.append(hashlib.sha256(file.read_bytes()).hexdigest()+'  '+name+'/'+file.relative_to(folder).as_posix())
    (out/'SHA256SUMS').write_text('\n'.join(rows)+'\n')
    if required_pass and channel in ('stable','nightly'):
        assets=out/'assets';assets.mkdir(exist_ok=True)
        for name,e in expected.items():
            if not e['required']:continue
            info=found[name];folder=folders[name]
            if e['platform']=='windows':
                filename=f'rustdesk-{info["upstream_version"]}-{info["variant"]}-windows-x86_64.zip'
                with zipfile.ZipFile(assets/filename,'w',zipfile.ZIP_DEFLATED) as z:
                    for f in sorted(folder.rglob('*')):
                        if f.is_file():z.write(f,f.relative_to(folder).as_posix())
                metadata_name='build-info-'+info['variant']+'.json'
            else:
                for package in sorted((folder/'packages').iterdir()):
                    filename=f'rustdesk-{info["upstream_version"]}-{info["variant"]}-{e["platform"]}-{e["arch"]}-{package.name}'
                    shutil.copy2(package,assets/filename)
                metadata_name='build-info-'+name+'.json'
                # Corresponding customization source and licence accompany native packages.
                with zipfile.ZipFile(assets/('source-'+name+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
                    for f in [folder/'LICENCE',folder/'SOURCE-README.md',folder/'source-manifest.json']+list((folder/'patches').rglob('*.patch')):
                        z.write(f,f.relative_to(folder).as_posix())
            shutil.copy2(folder/'build-info.json',assets/metadata_name)
        from scripts.platform.platform_package import checksums
        checksums(assets)
    print(json.dumps(report,indent=2))
    if errors:raise ValueError('Aggregate required gate FAIL')
    return report

def _release(root, publish, channel='stable'):
    if channel == 'nightly' and publish:
        raise ValueError('Nightly release is forbidden; only draft publication is allowed')
    if channel not in ('stable','nightly'):
        raise ValueError('Unsupported release channel')
    from scripts.upstream.resolve import api
    from scripts.release.github import request,gh
    repo='billradar/rustdesk-custom'
    if os.environ.get('GITHUB_REPOSITORY')!=repo:raise ValueError('Wrong release repository')
    os.environ['REQUIRE_ANDROID_PRODUCTION_SIGNING']='true' if channel in ('stable','nightly') else 'false'
    report=aggregate(root,channel,channel=='nightly')
    if report['result']!='PASS':raise ValueError('No complete supported aggregate')
    infos=[json.loads(p.read_text()) for p in root.rglob('build-info.json')]
    standard=next(i for i in infos if i['variant']=='standard' and i['platform']=='windows-x86_64')
    sos=next(i for i in infos if i['variant']=='sos' and i['platform']=='windows-x86_64')
    suffix='' if channel=='stable' else '-nightly'
    tag=f'v{standard["upstream_tag"].lstrip("v")}-custom.{standard["patch_revision"]}{suffix}'
    if api(f'repos/{repo}/releases/tags/{tag}',missing=True) or api(f'repos/{repo}/git/ref/tags/{tag}',missing=True):raise ValueError('No overwrite')
    existing=[r for r in (api(f'repos/{repo}/releases?per_page=100') or []) if r.get('name')==tag]
    if any(r.get('draft') for r in existing):raise ValueError('Existing revision draft')
    if any(not r.get('draft') for r in existing):raise ValueError('Existing revision release')
    from scripts.release.production import scan_job_log
    for j in api(f'repos/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}/jobs?per_page=100')['jobs']:
        if j['status']=='completed' and j['conclusion']=='success':scan_job_log(j['id'])
    directory=ROOT/'.work/qualification-aggregate/assets'
    notes='\\n'.join(['Upstream: rustdesk/rustdesk',f'Upstream Tag: {standard["upstream_tag"]}',f'Upstream SHA: {standard["upstream_sha"]}',f'Patch Set: {standard["patchset"]}',f'Common Patch Hash: {standard["common_patch_hash"]}',f'SOS Patch Hash: {sos["sos_patch_hash"]}',f'Custom Repository SHA: {standard["custom_repository_sha"]}',f'Prepared Source Run: {standard["prepare_run"]}',f'Build Run: {standard["build_run"]}',
        'Required Targets: '+','.join(sorted(report['targets'])),
        'Asset Inventory: '+json.dumps(sorted(p.name for p in directory.iterdir())),
        'Build / Package / Checksum / Architecture / Provenance: PASS',
        'Runtime/UI Validation: SKIPPED BY USER','Real Remote Session Validation: NOT TESTED','Desktop Code Signing: NOT ENABLED',
        'Android artifacts: PRODUCTION SIGNED / IDENTITY VERIFIED','Password Security V2: DEFERRED',
        'Embedded client configuration/password can be extracted by client owners.',
        'Release policy: '+('PUBLISHED RELEASE.' if publish else 'DRAFT ONLY; publication is a manual user decision.')])+'\\n'
    result=request('POST',f'repos/{repo}/releases',{'tag_name':tag,'target_commitish':standard['custom_repository_sha'],'name':tag,'body':notes,'draft':True,'prerelease':False})
    gh('release','upload',tag,*map(str,sorted(directory.iterdir())),'--repo',repo)
    expected_assets={p.name:p.stat().st_size for p in directory.iterdir()}
    uploaded={}
    for attempt in range(12):
        assets=api(f'repos/{repo}/releases/{result["id"]}/assets') or []
        uploaded={a['name']:a['size'] for a in assets if a.get('state')=='uploaded'}
        if uploaded==expected_assets: break
        if attempt<11:time.sleep(5)
    if uploaded!=expected_assets:
        raise ValueError('Incomplete release upload; remains unpublished: expected='+json.dumps(expected_assets,sort_keys=True)+' actual='+json.dumps(uploaded,sort_keys=True))
    final=request('PATCH',f'repos/{repo}/releases/{result["id"]}',{'draft':not publish,'body':notes+('Automation-State: published\\n' if publish else 'Automation-State: complete\\n')})
    if final['draft']!= (not publish): raise ValueError('Release state transition failed')

def draft(root, channel='stable'): _release(root, False, channel)
def release(root, channel='stable'): _release(root, True, channel)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['check','plan','aggregate','draft','release']);a.add_argument('--channel',default='nightly');a.add_argument('--experimental',action='store_true');a.add_argument('--root',type=Path,default=Path('.work/all-targets'));a=a.parse_args()
    if a.mode=='check':entries();print('Explicit platform metadata: PASS')
    elif a.mode=='plan':
        p=plan(a.channel,a.experimental);Path('.work').mkdir(exist_ok=True);Path('.work/target-plan.json').write_text(json.dumps(p,indent=2)+'\n')
        extra=[e for e in p['selected'] if e['platform']!='windows']
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:
                f.write('matrix='+json.dumps({'include':extra},separators=(',',':'))+'\ncount='+str(len(extra))+'\n')
    elif a.mode=='draft':draft(a.root,a.channel)
    elif a.mode=='release':release(a.root,a.channel)
    else:aggregate(a.root,a.channel,a.experimental)
