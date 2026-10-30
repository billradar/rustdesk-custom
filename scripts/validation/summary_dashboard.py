#!/usr/bin/env python3
"""Read-only actual-run evidence collection for the shared Summary renderer."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from scripts.validation import summary


def gh(*args):
    return subprocess.run(['gh',*args],check=True,capture_output=True,text=True,timeout=60).stdout


def api(path):
    return json.loads(gh('api',path))


def pages(path, key):
    rows=[]
    for page in range(1,101):
        data=api(path+('&' if '?' in path else '?')+f'per_page=100&page={page}')[key]
        rows.extend(data)
        if len(data)<100:return rows
    raise ValueError('Summary evidence pagination limit')


def read_artifact(repo,run_id,name,filename):
    with tempfile.TemporaryDirectory(prefix='summary-evidence-') as temp:
        gh('run','download',str(run_id),'--repo',repo,'--name',name,'--dir',temp)
        candidates=list(Path(temp).rglob(filename))
        if (len(candidates)!=1 or not candidates[0].resolve().is_relative_to(Path(temp).resolve())
                or candidates[0].is_symlink() or candidates[0].stat().st_size>1024*1024):
            return {}
        value=json.loads(candidates[0].read_text())
        return value if isinstance(value,dict) else {}


def snapshot(repo,run_id):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',repo) or not re.fullmatch('[1-9][0-9]*',str(run_id)):
        raise ValueError('Invalid Summary run identity')
    run=api(f'repos/{repo}/actions/runs/{run_id}')
    if run.get('repository',{}).get('full_name')!=repo or str(run.get('id'))!=str(run_id):
        raise ValueError('Summary run/source mismatch')
    from scripts.validation.build_reliability import latest_jobs
    jobs=latest_jobs(pages(f'repos/{repo}/actions/runs/{run_id}/jobs?filter=all','jobs'))
    return run,jobs


def collect(repo,run_id):
    run,jobs=snapshot(repo,run_id)
    upstream={}
    reports=[]
    try:
        artifacts=pages(f'repos/{repo}/actions/runs/{run_id}/artifacts','artifacts')
    except Exception:
        artifacts=[]
    available={a['name']:a for a in artifacts if not a.get('expired')}
    names=[(f'nightly-discovery-{run_id}','nightly-discovery.json'),
           (f'channel-discovery-{run_id}','channel.json')]
    locks=[name for name in available if re.fullmatch(f'stable-build-lock-{run_id}-[1-9][0-9]*',name)]
    if locks:names.append((max(locks,key=lambda n:int(n.rsplit('-',1)[1])),'stable-lock.json'))
    for name,filename in names:
        if name not in available:continue
        try:
            data=read_artifact(repo,run_id,name,filename)
            if (re.fullmatch('[0-9a-f]{40}',str(data.get('upstream_sha','')))
                    and (filename!='stable-lock.json' or
                         (data.get('custom_repository_sha')==run['head_sha'] and str(data.get('workflow_run'))==str(run_id)))):
                upstream=data
        except Exception:
            pass  # Missing or unreadable optional evidence must not invent a result.
    name=f'generation-compatibility-{run_id}'
    if name in available:
        try:
            data=read_artifact(repo,run_id,name,'compatibility-report.json')
            same_source = not data.get('upstream_sha') or not upstream or data['upstream_sha']==upstream['upstream_sha']
            if same_source:
                if data.get('upstream_sha'):
                    reports.append(data)
                    if not upstream:upstream={'upstream_sha':data['upstream_sha']}
                if data.get('upstream_version'):upstream['upstream_version']=data['upstream_version']
                if data.get('patchset') or data.get('selected'):upstream['patchset']=data.get('patchset') or data['selected']
        except Exception:
            pass
    # Older generation reports did not contain per-variant checks. Recover only
    # their real, same-source diagnostic JSON; never infer coverage from a green job.
    if not any(isinstance(r.get('variants'),dict) and r['variants'] for r in reports):
        for stage in ('preflight','flutter'):
            for variant in ('standard','sos'):
                name=f'{stage}-{variant}-report-{run_id}'
                if name not in available:continue
                try:
                    data=read_artifact(repo,run_id,name,'report.json')
                    if upstream.get('upstream_sha') and data.get('upstream_sha')==upstream['upstream_sha']:
                        reports.append(data)
                except Exception:
                    pass
    variants=summary.merge_compatibility(reports,upstream.get('upstream_sha'),upstream.get('patchset'))
    sdk={v:[] for v in variants}
    for job in jobs:
        match=re.search(r' / android-(?:x86_64|aarch64|armv7)-(standard|sos)$',job.get('name',''))
        if not match:continue
        steps=[s for s in job.get('steps',[]) if s.get('name')=='Prepare and verify Android SDK before native compilation']
        sdk[match.group(1)].append(summary.state(steps[0].get('conclusion')) if len(steps)==1 else 'NOT RUN')
    for variant,states in sdk.items():
        if states:variants[variant]['SDK Preflight']=summary.overall(states)
    return run,jobs,upstream,variants


def publish_run(repo,run_id,recovery=None,maximum=None,output=None):
    try:
        run,jobs,upstream,variants=collect(repo,run_id)
        evidence=dict(run=run,jobs=jobs,upstream=upstream,variants=variants)
        if recovery:evidence['recovery']=recovery
        if output:
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(evidence,indent=2)+'\n')
        return summary.publish('dashboard',summary.dashboard,run,jobs,upstream,variants,recovery,maximum,evidence)
    except Exception:
        print('Summary evidence is unavailable; original workflow results remain authoritative.')
        summary.publish('summary-unavailable',summary.card,'⚠️ Summary evidence unavailable',
                        [('Run ID',run_id),('Data status','NOT RUN — unavailable, not a pass')])
        return False


def main():
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    run=event['workflow_run']
    repo=os.environ['GITHUB_REPOSITORY']
    # This observer is read-only, including for PR results. Never check out a PR head.
    publish_run(repo,run['id'],output=Path('.work/dashboard/evidence.json'))


if __name__=='__main__':main()
