#!/usr/bin/env python3
"""Frozen generations and fail-closed selection, independent clean candidate clones."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parent.parent

def metadata(name):
    if not re.fullmatch(r'v[1-9][0-9]*', name):
        raise ValueError('Invalid patchset ID')
    return json.loads((ROOT / 'patchsets' / name / 'patchset.json').read_text())

def patch_hash(folder, name=None):
    name = name or os.environ.get('PATCHSET', 'v1')
    metadata(name)
    paths=sorted((ROOT/'patchsets'/name/folder).glob('*.patch'))
    if not paths: raise ValueError('Empty patch generation')
    d=hashlib.sha256()
    for p in paths: d.update(p.name.encode()+b'\0'+p.read_bytes().replace(b'\r\n',b'\n'))
    return d.hexdigest()

def verify(name):
    m=metadata(name)
    for folder in ('common','sos'):
        if patch_hash(folder,name)!=m['hashes'][folder]:
            raise ValueError('Patchset integrity mismatch: '+name+'/'+folder)
    return m

def mapped(sha):
    index=json.loads((ROOT/'patchsets/index.json').read_text())
    name=index['validated_mapping'].get(sha)
    if name: verify(name)
    return name

def probe(source, sha, name, base):
    from compatibility import contracts
    env=dict(os.environ,PATCHSET=name,UPSTREAM_EXPECTED_SHA=sha)
    result={'patchset':name,'status':'INCOMPATIBLE','checks':{}}
    verify(name)
    base.mkdir(parents=True,exist_ok=True)
    try:
        for variant in ('standard','sos'):
            tree=base/variant
            commands=[['git','clone','--quiet','--shared','--no-checkout',str(source),str(tree)],
                      ['git','-C',str(tree),'checkout','--quiet','--detach',sha],
                      ['git','-C',str(tree),'submodule','update','--init','--recursive'],
                      ['bash',str(ROOT/'scripts/apply-patches.sh'),str(tree),variant],
                      ['python3',str(ROOT/'scripts/verify-source.py'),str(tree),variant,'--automation','--static-only']]
            for command in commands:
                run=subprocess.run(command,env=env,text=True,capture_output=True)
                if run.returncode:
                    raise RuntimeError(run.stdout[-5000:]+run.stderr[-5000:])
            contracts(tree,variant,name)
            result['checks'][variant]='PATCH / CONFIG / STRUCTURAL API PASS'
        result['status']='PREFLIGHT_COMPATIBLE'
        result['coverage']='Static selection only; real Rust/Flutter/Bridge must pass downstream'
    except Exception as error: result['reason']=str(error)
    return result

def select(sha, source=None, report=None):
    if not re.fullmatch('[0-9a-f]{40}',sha): raise ValueError('Exact SHA required')
    index=json.loads((ROOT/'patchsets/index.json').read_text())
    fixed=mapped(sha)
    names=[fixed] if fixed else index['candidates']
    ROOT.joinpath('.work').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='resolver-',dir=ROOT/'.work') as tmp:
        tmp=Path(tmp)
        if source is None:
            source=tmp/'upstream'
            subprocess.run(['bash',str(ROOT/'scripts/prepare.sh'),sha,str(source)],check=True,stdout=subprocess.DEVNULL)
        rows=[probe(Path(source).resolve(),sha,name,tmp/name) for name in names]
        selected=next((r['patchset'] for r in rows if r['status']=='PREFLIGHT_COMPATIBLE'),None)
        data={'upstream_sha':sha,'known_validated_mapping':bool(fixed),'patchsets':rows,'selected':selected,
              'overall':'PREFLIGHT_PASS' if selected else 'FAIL','runtime_ui':'SKIPPED BY USER','real_remote_session':'NOT TESTED'}
        if report:
            report=Path(report);report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(data,indent=2)+'\n')
        print(json.dumps(data,indent=2))
        if not selected: raise RuntimeError('NO COMPATIBLE PATCH SET; no build or release allowed')
        return selected

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('sha');p.add_argument('--source',type=Path);p.add_argument('--report',default='.work/patchset-selection.json');args=p.parse_args()
    name=select(args.sha,args.source,args.report)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('patchset='+name+'\n')
