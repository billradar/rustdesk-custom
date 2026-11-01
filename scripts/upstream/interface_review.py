#!/usr/bin/env python3
"""Record unknown interfaces and propose report-only PRs; never approve profiles."""
import argparse
import base64
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from scripts.build import build_adapter
from scripts.upstream.patchsets import patchset_for_version, patch_hash
from scripts.validation.compatibility import contracts

ROOT=Path(__file__).resolve().parents[2]
REPOSITORY='billradar/rustdesk-custom'
SCHEMA='upstream-interface-review-v1'


def output(key,value):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write(key+'='+value+'\n')


def collect(source, upstream_sha, out):
    if not re.fullmatch('[0-9a-f]{40}',upstream_sha):raise ValueError('Exact upstream SHA required')
    actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if actual!=upstream_sha:raise ValueError('Source identity mismatch')
    if subprocess.check_output(['git','-C',str(source),'status','--porcelain','--ignore-submodules=none'],text=True).strip():
        raise ValueError('Source review requires clean upstream')
    known=json.loads((ROOT/'metadata/build/adapter-profiles.json').read_text())['profiles']
    try:
        profile,critical=build_adapter.inspect(source)
        inspection_error=None
    except Exception as e:
        profile=None;critical=None;inspection_error=str(e)
    if profile and any(p['signature']==profile['signature'] for p in known):
        output('review_needed','false');return None
    base=known[-1]
    # Public diagnostics only; the read job never loads production configuration.
    packet={'schema':SCHEMA,'approval':'REQUIRED / NOT APPROVED','upstream_repository':'rustdesk/rustdesk',
        'upstream_sha':upstream_sha,'custom_repository_sha':os.environ['GITHUB_SHA'],
        'workflow_run':os.environ['GITHUB_RUN_ID'],'observed_profile':profile,
        'inspection_error':inspection_error,'critical':critical,'compared_profile':base['id'],
        'checks':{'interface':'UNKNOWN / BLOCKED','patches':{},'rust_compile':'NOT RUN',
                  'bridge':'NOT RUN','flutter_analyze':'NOT RUN','runtime':'NOT TESTED'}}
    old=json.dumps(base.get('critical',{}),indent=2,sort_keys=True).splitlines()
    compared={k:critical[k] for k in base.get('critical',{}) if critical and k in critical} if critical else None
    new=json.dumps(compared,indent=2,sort_keys=True).splitlines()
    packet['upstream_compare_url']='https://github.com/rustdesk/rustdesk/compare/'+base['reviewed_upstream_sha']+'...'+upstream_sha
    packet['critical_diff']='\n'.join(difflib.unified_diff(old,new,fromfile=base['id'],tofile=upstream_sha,lineterm=''))
    if profile:
        try:
            patchset=patchset_for_version(profile['upstream_version'])
        except (ValueError, KeyError) as e:
            packet['patchset_error']=str(e)
            patchset=None
    else:
        patchset=None
    if patchset:
        packet['patchset']=patchset
        packet['patch_hashes']={k:patch_hash(k,patchset) for k in ['common','sos']}
        for variant in ['standard','sos']:
            with tempfile.TemporaryDirectory() as tmp:
                tree=Path(tmp)/'source';shutil.copytree(source,tree,symlinks=True)
                p=subprocess.run(['bash',str(ROOT/'scripts/source/apply_patches.sh'),str(tree),variant],
                    env=dict(os.environ,PATCHSET=patchset),capture_output=True,text=True)
                result={'patch_apply':'PASS' if p.returncode==0 else 'FAIL','api_structure':'NOT RUN'}
                if p.returncode:
                    # Only file/hunk diagnostics, never an environment dump.
                    result['diagnostic']=(p.stdout+p.stderr)[-6000:]
                else:
                    try:contracts(tree,variant,patchset);result['api_structure']='PASS'
                    except Exception as e:result.update(api_structure='FAIL',diagnostic=str(e))
                packet['checks']['patches'][variant]=result
    out.mkdir(parents=True,exist_ok=True)
    (out/'proposal.json').write_text(json.dumps(packet,indent=2)+'\n')
    output('review_needed','true')
    print('Unknown interface recorded; approval remains REQUIRED')
    return packet


def request(path, method='GET', data=None, missing=False):
    req=urllib.request.Request('https://api.github.com/repos/'+REPOSITORY+'/'+path,
        headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+os.environ['GH_TOKEN'],
                 'User-Agent':'rustdesk-custom-interface-review'},method=method,
        data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        if missing and e.code==404:return None
        raise


def validate_report(p):
    """Validate report contents without claiming they belong to the current run."""
    if not isinstance(p,dict):raise ValueError('Invalid review report')
    if p.get('schema')!=SCHEMA or p.get('approval')!='REQUIRED / NOT APPROVED' or p.get('upstream_repository')!='rustdesk/rustdesk':
        raise ValueError('Invalid/unapproved review packet')
    for key in ['upstream_sha','custom_repository_sha']:
        if not re.fullmatch('[0-9a-f]{40}',str(p.get(key,''))):raise ValueError('Invalid packet identity')
    if not re.fullmatch('[1-9][0-9]*',str(p.get('workflow_run',''))):raise ValueError('Invalid report run')
    if not isinstance(p.get('checks'),dict):raise ValueError('Missing report checks')
    if p['checks'].get('interface')!='UNKNOWN / BLOCKED':raise ValueError('Review must not claim approval')
    if p['checks'].get('rust_compile')!='NOT RUN' or p['checks'].get('bridge')!='NOT RUN' or p['checks'].get('flutter_analyze')!='NOT RUN' or p['checks'].get('runtime')!='NOT TESTED':
        raise ValueError('Review must not invent compilation/runtime validation')
    if p.get('observed_profile') is not None:
        if (not isinstance(p['observed_profile'],dict) or not isinstance(p.get('critical'),dict)
                or not re.fullmatch('[0-9a-f]{64}',str(p['observed_profile'].get('signature','')))
                or build_adapter.digest(p['critical'])!=p['observed_profile']['signature']):
            raise ValueError('Observed interface signature mismatch')


def validate_packet(p):
    validate_report(p)
    if p['custom_repository_sha']!=os.environ['GITHUB_SHA'] or str(p['workflow_run'])!=os.environ['GITHUB_RUN_ID']:
        raise ValueError('Review packet is not from this exact run/commit')


def report_identity(packet):
    return packet['observed_profile']['signature'] if packet.get('observed_profile') else packet['upstream_sha']


def recover_report(current, head, signature):
    """Read an immutable, report-only branch; never rewrite its historical data."""
    if not re.fullmatch('[0-9a-f]{40}',head):raise ValueError('Invalid review branch head')
    compare=request('compare/'+current+'...'+head)
    files=compare.get('files',[])
    if (len(files)!=1 or files[0].get('status')!='added'
            or not re.fullmatch(r'docs/upstream-interface-reviews/[0-9a-f]{40}\.json',files[0].get('filename',''))):
        raise ValueError('Existing review branch has unexpected changes; refusing reuse')
    path=files[0]['filename']
    tree_sha=request('git/commits/'+head)['tree']['sha']
    tree=request('git/trees/'+tree_sha+'?recursive=1')
    entries=[entry for entry in tree.get('tree',[]) if entry.get('path')==path]
    if (tree.get('truncated',True) or len(entries)!=1 or entries[0].get('mode')!='100644'
            or entries[0].get('type')!='blob' or entries[0].get('sha')!=files[0].get('sha')):
        raise ValueError('Existing review report is not a verified regular JSON file')
    blob=request('git/blobs/'+entries[0]['sha'])
    if (blob.get('encoding')!='base64' or not isinstance(blob.get('size'),int)
            or not 0<blob['size']<=1024*1024 or len(blob.get('content',''))>2*1024*1024):
        raise ValueError('Existing review report is oversized or invalid')
    raw=base64.b64decode(''.join(blob['content'].split()),validate=True)
    if len(raw)!=blob['size']:raise ValueError('Existing review report size mismatch')
    report=json.loads(raw)
    validate_report(report)
    if path!='docs/upstream-interface-reviews/'+report['upstream_sha']+'.json' or report_identity(report)!=signature:
        raise ValueError('Existing review report has a different source or interface identity')
    run=request('actions/runs/'+str(report['workflow_run']))
    if (run.get('head_sha')!=report['custom_repository_sha'] or run.get('head_branch')!='main'
            or run.get('event') not in ('schedule','workflow_dispatch')
            or run.get('path')!='.github/workflows/upstream-main-compatibility.yml'
            or run.get('repository',{}).get('full_name')!=REPOSITORY):
        raise ValueError('Existing review report is not from the trusted discovery workflow')
    return report


def publish(packet):
    # Even an edited workflow cannot accidentally use this path from a PR or another branch.
    if os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY or os.environ.get('GITHUB_REF')!='refs/heads/main' or os.environ.get('GITHUB_EVENT_NAME') not in ['schedule','workflow_dispatch']:
        raise ValueError('Review PR writes require protected main scheduled/manual context')
    validate_packet(packet)
    signature=report_identity(packet)
    if not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}',signature):raise ValueError('Invalid review identity')
    branch='automation/upstream-interface-'+signature
    owner=REPOSITORY.split('/')[0]
    existing=request('pulls?state=all&head='+owner+':'+branch+'&base=main')
    if existing:
        print('Review already recorded: '+existing[0]['html_url']);return existing[0]['html_url']
    # The only proposed change is a non-executable report, never adapter-profiles.json.
    path='docs/upstream-interface-reviews/'+packet['upstream_sha']+'.json'
    current=request('git/ref/heads/main')['object']['sha']
    if current!=os.environ['GITHUB_SHA']:raise ValueError('Main advanced; retry on its current trusted revision')
    ref=request('git/ref/heads/'+branch,missing=True)
    report=packet
    if ref:
        # Recover a PR-creation failure without resetting/replacing the branch.
        head=ref['object']['sha']
        report=recover_report(current,head,signature)
    else:
        parent=request('git/commits/'+current)
        tree=request('git/trees','POST',{'base_tree':parent['tree']['sha'],'tree':[{'path':path,'mode':'100644','type':'blob','content':json.dumps(packet,indent=2)+'\n'}]})
        commit=request('git/commits','POST',{'message':'docs: record unknown upstream interface '+packet['upstream_sha'][:12],
            'tree':tree['sha'],'parents':[current]})
        request('git/refs','POST',{'ref':'refs/heads/'+branch,'sha':commit['sha']})
        head=commit['sha']
    if (request('git/ref/heads/main')['object']['sha']!=current
            or request('git/ref/heads/'+branch)['object']['sha']!=head):
        raise ValueError('Review refs changed during validation; retry without overwriting them')
    body=('Unknown upstream interface detected at `'+report['upstream_sha']+'`.\n\n'
        'This report records the observed signature, reviewed-baseline diff and independent Standard/SOS patch/application structure checks. '
        'It does not modify the approved profile list, select a new patch generation, authorize publication, or claim successful compilation/runtime testing. '
        'A maintainer must inspect the changes and explicitly approve the interface before the normal gate can pass.\n\n'
        'Stored report discovery run: https://github.com/'+REPOSITORY+'/actions/runs/'+str(report['workflow_run']))
    if report is not packet:
        body+=('\n\nRecovered the existing report without changing its branch or contents. '
            'Current discovery at `'+packet['upstream_sha']+'` has the same review identity; '
            'the stored checks apply only to the historical report source, not the current discovery.\n\n'
            'Current discovery run: https://github.com/'+REPOSITORY+'/actions/runs/'+os.environ['GITHUB_RUN_ID'])
    pr=request('pulls','POST',{'title':'Review unknown upstream build interface '+signature[:12],
        'head':branch,'base':'main','body':body,'draft':True})
    print('Created review draft: '+pr['html_url']);return pr['html_url']


if __name__=='__main__':
    a=argparse.ArgumentParser();sub=a.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('collect');p.add_argument('--source',type=Path,required=True);p.add_argument('--sha',required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('publish');p.add_argument('--packet',type=Path,required=True)
    args=a.parse_args()
    if args.mode=='collect':collect(args.source,args.sha,args.out)
    else:publish(json.loads(args.packet.read_text()))
