#!/usr/bin/env python3
"""Explicit targets and cross-platform fan-in; support requires reviewed Actions evidence."""
import argparse, hashlib, json, os, re, shutil, subprocess, time
from pathlib import Path
from scripts.upstream.patchsets import patch_hash
ROOT=Path(__file__).resolve().parents[2]
FORBIDDEN={'android','ios','web'}
def target(e):return '-'.join((e['platform'],e['arch'],e['variant']))
def entries():
    rows=json.loads((ROOT/'metadata/platform/matrix.json').read_text())['entries'];seen=set()
    reviewed=json.loads((ROOT/'metadata/platform/adapter-profiles.json').read_text())['audited']
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

def build_provenance_identity(i):
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
            if build_provenance_identity(i)!=build_provenance_identity(first):raise ValueError('PROVENANCE: cross-platform source/generation mismatch')
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
                packages_dir=folder/'packages'
                if not packages_dir.is_dir():
                    raise ValueError('PACKAGE: missing validated Windows installer directory')
                packages=sorted(p for p in packages_dir.iterdir() if p.is_file())
                if {p.suffix.lower() for p in packages} != {'.exe','.msi'}:
                    raise ValueError('PACKAGE: Windows release requires exactly one EXE and one MSI')
                for package in packages:
                    filename=f'rustdesk-{info["upstream_version"]}-{info["variant"]}-windows-x86_64{package.suffix.lower()}'
                    shutil.copy2(package,assets/filename)
            else:
                packages_dir=folder/'packages'
                if not packages_dir.is_dir():
                    raise ValueError('PACKAGE: missing validated native package directory')
                allowed_suffixes={'android': {'.apk'}, 'linux': {'.deb', '.rpm'}, 'macos': {'.dmg'}}[e['platform']]
                for package in sorted(packages_dir.iterdir()):
                    if not package.is_file():
                        raise ValueError('PACKAGE: unexpected non-file package entry')
                    if package.suffix.lower() not in allowed_suffixes:
                        raise ValueError('PACKAGE: non-binary release asset is forbidden: '+package.name)
                    prefix=f'{info["variant"]}-rustdesk-{info["upstream_version"]}-'
                    package_tail=package.name
                    if package_tail.startswith(prefix):
                        package_tail=package_tail[len(prefix):]
                    filename=f'rustdesk-{info["upstream_version"]}-{info["variant"]}-{e["platform"]}-{e["arch"]}-{package_tail}'
                    shutil.copy2(package,assets/filename)
        from scripts.platform.platform_package import checksums
        checksums(assets)
        public_assets=sorted(p.name for p in assets.iterdir())
        forbidden=[name for name in public_assets if name.lower().endswith('.json') or name.startswith('source-') or name.startswith('build-info-')]
        if forbidden:
            raise ValueError('PACKAGE: non-public release assets generated: '+', '.join(forbidden))
    print(json.dumps(report,indent=2))
    if errors:raise ValueError('Aggregate required gate FAIL')
    return report

def gh_json(path):
    p=subprocess.run(["gh","api",path],check=True,capture_output=True,text=True,env=os.environ)
    return json.loads(p.stdout)


def qualification_identity(record):
    return (
        record.get("upstream_repository"),
        record.get("upstream_sha"),
        record.get("upstream_ref"),
        record.get("patchset"),
        record.get("common_patch_hash"),
        record.get("sos_patch_hash"),
    )


def expected_qualification_identity(upstream_sha, upstream_ref, patchset):
    return (
        "rustdesk/rustdesk",
        upstream_sha,
        upstream_ref,
        patchset,
        patch_hash("common", patchset),
        patch_hash("sos", patchset),
    )


def validate_ci_record(record, repo, run_id, custom_sha=None, upstream_sha=None, upstream_ref=None, patchset=None):
    if record.get("schema") != "ci-qualification-v1" or record.get("qualified") is not True:
        raise ValueError("Qualification artifact schema/qualified flag mismatch")
    if record.get("upstream_repository") != "rustdesk/rustdesk":
        raise ValueError("Qualification upstream repository mismatch")
    if record.get("event") != "workflow_dispatch":
        raise ValueError("Qualification event mismatch")
    if record.get("workflow_run_id") != run_id:
        raise ValueError("Qualification workflow run mismatch")
    if custom_sha is not None and record.get("custom_repository_sha") != custom_sha:
        raise ValueError("Qualification custom repository SHA mismatch")
    if upstream_sha is not None and record.get("upstream_sha") != upstream_sha:
        raise ValueError("Qualification upstream SHA mismatch")
    if upstream_ref is not None and record.get("upstream_ref") != upstream_ref:
        raise ValueError("Qualification upstream ref mismatch")
    selected_patchset = patchset or record.get("patchset")
    if not isinstance(selected_patchset, str) or not selected_patchset:
        raise ValueError("Qualification missing patchset")
    if record.get("patchset") != selected_patchset:
        raise ValueError("Qualification patchset mismatch")
    if record.get("common_patch_hash") != patch_hash("common", selected_patchset):
        raise ValueError("Qualification common patch hash mismatch")
    if record.get("sos_patch_hash") != patch_hash("sos", selected_patchset):
        raise ValueError("Qualification SOS patch hash mismatch")
    mode = record.get("qualification_mode", "legacy")
    if mode == "stable":
        owner = record.get("stable_owner_run_id")
        stable_sha = record.get("stable_custom_sha")
        if not isinstance(owner, int) or owner <= 0:
            raise ValueError("Stable qualification missing owner run ID")
        if not isinstance(stable_sha, str) or len(stable_sha) != 40:
            raise ValueError("Stable qualification missing owner custom SHA")
        if stable_sha != record.get("custom_repository_sha"):
            raise ValueError("Stable qualification owner/custom SHA mismatch")
    elif mode not in ("manual", "legacy"):
        raise ValueError("Unknown qualification mode")
    return record


def _download_qualification(repo, run_id, artifact_name):
    target=Path(".work/qualification-lookup")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    subprocess.run(
        ["gh","run","download",str(run_id),"-R",repo,"-n",artifact_name,"-D",str(target)],
        check=True,env=os.environ
    )
    files=list(target.rglob("ci-qualification.json"))
    if len(files)!=1:
        raise ValueError("Qualification artifact must contain exactly one record")
    return json.loads(files[0].read_text())


def _workflow_dispatch_success_runs(repo):
    rows=[]
    for page in range(1,11):
        data=gh_json(
            f"repos/{repo}/actions/workflows/ci.yml/runs"
            f"?event=workflow_dispatch&status=success&branch=main&per_page=100&page={page}"
        )
        batch=data.get("workflow_runs",[])
        rows.extend(batch)
        if len(batch)<100:
            break
    return rows


def lookup_ci_qualification(repo, custom_sha, upstream_sha, upstream_ref, patchset):
    if len(custom_sha)!=40 or len(upstream_sha)!=40:
        raise ValueError("Invalid release SHA")
    expected=expected_qualification_identity(upstream_sha, upstream_ref, patchset)
    invalid_reason=None
    for run in _workflow_dispatch_success_runs(repo):
        run_id=run.get("id")
        head_sha=run.get("head_sha")
        if not run_id or run.get("head_branch")!="main":
            continue
        artifacts=gh_json(
            f"repos/{repo}/actions/runs/{run_id}/artifacts?name=ci-qualification-{head_sha}&per_page=100"
        ).get("artifacts",[])
        if not artifacts or all(a.get("expired") for a in artifacts):
            if head_sha==custom_sha:
                invalid_reason="Successful CI run for this custom revision has no usable qualification artifact"
            continue
        for artifact in artifacts:
            if artifact.get("expired"):
                continue
            record=None
            try:
                record=_download_qualification(repo,run_id,artifact["name"])
                identity=qualification_identity(record)
                if identity==expected:
                    validate_ci_record(
                        record,repo,run_id,upstream_sha=upstream_sha,
                        upstream_ref=upstream_ref,patchset=patchset
                    )
                    return {"status":"FOUND","record":record,"workflow_run_id":run_id}
                if (
                    record.get("custom_repository_sha")==custom_sha
                    or (
                        record.get("upstream_repository")=="rustdesk/rustdesk"
                        and (
                            record.get("upstream_sha")==upstream_sha
                            or record.get("upstream_ref")==upstream_ref
                        )
                    )
                ):
                    invalid_reason="Candidate qualification identity mismatch"
            except Exception as exc:
                if (
                    head_sha==custom_sha
                    or (
                        isinstance(record,dict)
                        and (
                            record.get("upstream_sha")==upstream_sha
                            or record.get("upstream_ref")==upstream_ref
                        )
                    )
                ):
                    invalid_reason=str(exc)
    if invalid_reason:
        return {"status":"INVALID","reason":invalid_reason}
    return {"status":"MISSING"}


def verify_ci(repo,custom_sha,upstream_sha,upstream_ref,patchset=None,workflow_run_id=None):
    if len(custom_sha)!=40 or len(upstream_sha)!=40:
        raise ValueError("Invalid release SHA")
    if workflow_run_id is None:
        runs=gh_json(
            f"repos/{repo}/actions/workflows/ci.yml/runs"
            f"?head_sha={custom_sha}&event=workflow_dispatch&status=success&per_page=100"
        ).get("workflow_runs",[])
        candidates=[r for r in runs if r.get("head_sha")==custom_sha and r.get("head_branch")=="main"]
    else:
        candidates=[gh_json(f"repos/{repo}/actions/runs/{workflow_run_id}")]
    if not candidates:
        raise ValueError("No successful CI qualification run for the requested qualification identity")
    last_error=None
    for run in candidates:
        run_id=run["id"]
        if run.get("head_branch")!="main" or run.get("event")!="workflow_dispatch" or run.get("conclusion")!="success":
            last_error=ValueError("Qualification workflow provenance mismatch")
            continue
        artifact_name=f"ci-qualification-{run.get('head_sha')}"
        artifacts=gh_json(
            f"repos/{repo}/actions/runs/{run_id}/artifacts?name={artifact_name}&per_page=100"
        ).get("artifacts",[])
        usable=[a for a in artifacts if not a.get("expired")]
        if not usable:
            last_error=ValueError("Successful CI workflow exists, but no exact qualification artifact was found")
            continue
        try:
            record=_download_qualification(repo,run_id,artifact_name)
            if not re.fullmatch(r'[0-9a-f]{40}', str(record.get('custom_repository_sha',''))):
                raise ValueError('Qualification custom repository SHA missing or invalid')
            validate_ci_record(
                record,repo,run_id,custom_sha=None,
                upstream_sha=upstream_sha,upstream_ref=upstream_ref,
                patchset=patchset
            )
            if qualification_identity(record)!=expected_qualification_identity(
                upstream_sha,upstream_ref,record["patchset"]
            ):
                raise ValueError("Qualification identity mismatch")
            return record
        except Exception as exc:
            last_error=exc
            if workflow_run_id is not None:
                break
    raise last_error or ValueError("No exact qualification artifact was found")

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
    notes='\n'.join(['Upstream: rustdesk/rustdesk',f'Upstream Tag: {standard["upstream_tag"]}',f'Upstream SHA: {standard["upstream_sha"]}',f'Patch Set: {standard["patchset"]}',f'Common Patch Hash: {standard["common_patch_hash"]}',f'SOS Patch Hash: {sos["sos_patch_hash"]}',f'Custom Repository SHA: {standard["custom_repository_sha"]}',f'Prepared Source Run: {standard["prepare_run"]}',f'Build Run: {standard["build_run"]}',
        'Required Targets: '+','.join(sorted(report['targets'])),
        'Asset Inventory: '+json.dumps(sorted(p.name for p in directory.iterdir())),
        'Build / Package / Checksum / Architecture / Provenance: PASS',
        'Runtime/UI Validation: SKIPPED BY USER','Real Remote Session Validation: NOT TESTED','Desktop Code Signing: NOT ENABLED',
        'Android artifacts: PRODUCTION SIGNED / IDENTITY VERIFIED','Password Security V2: DEFERRED',
        'Embedded client configuration/password can be extracted by client owners.',
        'Release policy: '+('PUBLISHED RELEASE.' if publish else 'DRAFT ONLY; publication is a manual user decision.')])+'\n'
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
    final=request('PATCH',f'repos/{repo}/releases/{result["id"]}',{'draft':not publish,'body':notes+('Automation-State: published\n' if publish else 'Automation-State: complete\n')})
    if final['draft']!= (not publish): raise ValueError('Release state transition failed')

def publish_existing_draft(channel='stable'):
    if channel != 'stable':
        raise ValueError('Only Stable supports publishing an existing completed draft')
    from scripts.release.github import request
    repo='billradar/rustdesk-custom'
    if os.environ.get('GITHUB_REPOSITORY') != repo:
        raise ValueError('Wrong release repository')
    tag=os.environ.get('RELEASE_TAG','')
    if not re.fullmatch(r'v[0-9]+\\.[0-9]+\\.[0-9]+-custom\\.[1-9][0-9]{0,5}',tag):
        raise ValueError('Invalid existing Stable release tag')
    from scripts.release.channel import matching_drafts
    drafts=matching_drafts(tag)
    if len(drafts) != 1:
        raise ValueError('Expected exactly one existing Stable draft')
    existing=drafts[0]
    body=existing.get('body') or ''
    if not existing.get('draft') or existing.get('prerelease'):
        raise ValueError('Existing release is not a publishable draft')
    if 'Automation-State: complete' not in body:
        raise ValueError('Existing draft is not marked complete')
    if 'Build / Package / Checksum / Architecture / Provenance: PASS' not in body:
        raise ValueError('Existing draft missing complete aggregate marker')
    final=request(
        'PATCH',
        f'repos/{repo}/releases/{existing["id"]}',
        {'draft':False,'prerelease':False,'body':body+'Automation-State: published\n'}
    )
    if final.get('draft') is not False:
        raise ValueError('Existing Stable draft publication failed')
    print(f'Published existing Stable draft: {tag}')

def draft(root, channel='stable'): _release(root, False, channel)
def release(root, channel='stable'): _release(root, True, channel)

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('mode',choices=['check','plan','aggregate','draft','release','publish-existing','lookup','verify-ci'])
    a.add_argument('--channel',choices=['stable','nightly'],default='stable')
    a.add_argument('--experimental',action='store_true')
    a.add_argument('--root',type=Path,default=Path('.work/all-targets'))
    a.add_argument('--repository',default=os.environ.get('GITHUB_REPOSITORY',''))
    a.add_argument('--custom-sha')
    a.add_argument('--upstream-sha')
    a.add_argument('--upstream-ref')
    a.add_argument('--patchset')
    a.add_argument('--workflow-run-id',type=int)
    a.add_argument('--output',type=Path,default=Path('.work/ci-qualification.json'))
    a=a.parse_args()
    if a.mode=='check':
        entries();print('Explicit platform metadata: PASS')
    elif a.mode=='plan':
        p=plan(a.channel,a.experimental);Path('.work').mkdir(exist_ok=True);target_plan=Path('.work/target-plan.json');target_plan.write_text(json.dumps(p,indent=2)+'\n');json.loads(target_plan.read_text())
        extra=[e for e in p['selected'] if e['platform']!='windows']
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:
                f.write('matrix='+json.dumps({'include':extra},separators=(',',':'))+'\ncount='+str(len(extra))+'\n')
    elif a.mode=='draft':draft(a.root,a.channel)
    elif a.mode=='release':release(a.root,a.channel)
    elif a.mode=='publish-existing':publish_existing_draft(a.channel)
    elif a.mode=='lookup':
        if not all((a.custom_sha,a.upstream_sha,a.upstream_ref,a.patchset)):
            raise SystemExit('lookup requires --custom-sha, --upstream-sha, --upstream-ref and --patchset')
        result=lookup_ci_qualification(a.repository,a.custom_sha,a.upstream_sha,a.upstream_ref,a.patchset)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,indent=2)+'\n')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as out:
                out.write(f"status={result['status']}\n")
                out.write(f"patchset={a.patchset}\n")
                if result.get('workflow_run_id'):
                    out.write(f"workflow_run_id={result['workflow_run_id']}\n")
                if result.get('record',{}).get('custom_repository_sha'):
                    out.write(f"qualification_custom_sha={result['record']['custom_repository_sha']}\n")
                if result.get('reason'):
                    out.write("reason="+result['reason'].replace('\n',' ')+"\n")
    elif a.mode=='verify-ci':
        if not all((a.custom_sha,a.upstream_sha,a.upstream_ref)):
            raise SystemExit('verify-ci requires --custom-sha, --upstream-sha and --upstream-ref')
        record=verify_ci(a.repository,a.custom_sha,a.upstream_sha,a.upstream_ref,a.patchset,a.workflow_run_id)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(record,indent=2)+'\n')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as out:
                out.write(f"patchset={record['patchset']}\n")
                out.write(f"upstream_version={record['upstream_version']}\n")
                out.write(f"workflow_run_id={record['workflow_run_id']}\n")
                out.write(f"custom_repository_sha={record['custom_repository_sha']}\n")
    else:
        aggregate(a.root,a.channel,a.experimental)
