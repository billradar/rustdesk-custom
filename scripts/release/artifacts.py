"""Attempt-aware report lookup; immutable successful build payloads keep their names."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def select_name(rows, base, maximum_attempt):
    if type(maximum_attempt) is not int or maximum_attempt < 1:
        raise ValueError('Invalid artifact run attempt')
    found={}
    for row in rows:
        name=row.get('name','')
        if row.get('expired'):
            continue
        match=re.fullmatch(re.escape(base)+r'-attempt-([1-9][0-9]*)',name)
        attempt=int(match.group(1)) if match else 0 if name==base else None
        if attempt is None or attempt>maximum_attempt:
            continue
        if attempt in found:
            raise ValueError('Ambiguous report artifact: '+base)
        found[attempt]=name
    return found[max(found)] if found else None


def api(path):
    return json.loads(subprocess.check_output(['gh','api',path],text=True,timeout=60))


def download(repo, run_id, base, destination):
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo)
            or not re.fullmatch(r'[1-9][0-9]*',str(run_id))):
        raise ValueError('Invalid report artifact source')
    run=api(f'repos/{repo}/actions/runs/{run_id}')
    if str(run.get('id'))!=str(run_id) or run.get('repository',{}).get('full_name')!=repo:
        raise ValueError('Report artifact run/repository mismatch')
    rows=[]
    for page in range(1,101):
        batch=api(f'repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100&page={page}')['artifacts']
        rows.extend(batch)
        if len(batch)<100:
            break
    else:
        raise ValueError('Report artifact pagination limit')
    name=select_name(rows,base,run['run_attempt'])
    if name is None:
        raise ValueError('Report artifact unavailable: '+base)
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError('Report download destination must be empty')
    subprocess.run(['gh','run','download',str(run_id),'--repo',repo,'--name',name,
                    '--dir',str(destination)],check=True,capture_output=True,text=True,timeout=60)
    return name


def compatibility_reports(directory, run_id, maximum_attempt):
    """Select the newest report per stage/variant, including reused prior successes."""
    directory=Path(directory)
    bases=set()
    rows=[]
    for path in directory.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        match=re.fullmatch(r'((?:preflight|flutter)-(?:standard|sos)-report-'+re.escape(str(run_id))+r')(?:-attempt-[1-9][0-9]*)?',path.name)
        if match:
            bases.add(match.group(1));rows.append({'name':path.name})
    reports=[]
    for base in sorted(bases):
        name=select_name(rows,base,maximum_attempt)
        if name is None:
            continue
        root=directory/name
        paths=list(root.rglob('report.json'))
        if (len(paths)!=1 or paths[0].is_symlink() or not paths[0].resolve().is_relative_to(root.resolve())
                or paths[0].stat().st_size>1024*1024):
            raise ValueError('Missing/ambiguous compatibility report: '+name)
        value=json.loads(paths[0].read_text())
        if not isinstance(value,dict):
            raise ValueError('Invalid compatibility report: '+name)
        reports.append(value)
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True);parser.add_argument('--run',required=True)
    parser.add_argument('--base',required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    print('Downloaded report artifact: '+download(args.repo,args.run,args.base,args.destination))
