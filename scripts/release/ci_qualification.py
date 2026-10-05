#!/usr/bin/env python3
"""Verify that Stable CD consumes an exact, successful CI qualification."""
import argparse, json, os, shutil, subprocess
from pathlib import Path
from scripts.upstream.patchsets import patch_hash

def gh_json(path):
    p=subprocess.run(["gh","api",path],check=True,capture_output=True,text=True,env=os.environ)
    return json.loads(p.stdout)

def verify(repo,custom_sha,upstream_sha,upstream_ref):
    if len(custom_sha)!=40 or len(upstream_sha)!=40:
        raise ValueError("Invalid release SHA")
    runs=gh_json(f"repos/{repo}/actions/workflows/ci.yml/runs?head_sha={custom_sha}&event=workflow_dispatch&status=success&per_page=100").get("workflow_runs",[])
    candidates=[r for r in runs if r.get("head_sha")==custom_sha and r.get("head_branch")=="main"]
    if not candidates:
        raise ValueError("No successful CI qualification run for this custom revision; run CI workflow_dispatch on main with the exact Stable upstream ref first")
    for run in candidates:
        run_id=run["id"]
        artifacts=gh_json(f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100").get("artifacts",[])
        wanted=f"ci-qualification-{custom_sha}"
        if not [a for a in artifacts if a.get("name")==wanted and not a.get("expired")]:
            continue
        target=Path(".work/qualification")
        if target.exists(): shutil.rmtree(target)
        target.mkdir(parents=True)
        subprocess.run(["gh","run","download",str(run_id),"-R",repo,"-n",wanted,"-D",str(target)],check=True,env=os.environ)
        files=list(target.rglob("ci-qualification.json"))
        if len(files)!=1: raise ValueError("Qualification artifact must contain exactly one record")
        record=json.loads(files[0].read_text())
        expected={"schema":"ci-qualification-v1","qualified":True,"custom_repository_sha":custom_sha,
                  "upstream_repository":"rustdesk/rustdesk","upstream_sha":upstream_sha,
                  "upstream_ref":upstream_ref,"event":"workflow_dispatch"}
        for key,value in expected.items():
            if record.get(key)!=value: raise ValueError(f"Qualification identity mismatch: {key}")
        if record.get("workflow_run_id")!=run_id: raise ValueError("Qualification workflow run mismatch")
        patchset=record.get("patchset")
        if not isinstance(patchset,str) or not patchset: raise ValueError("Qualification missing patchset")
        if record.get("common_patch_hash")!=patch_hash("common",patchset): raise ValueError("Qualification common patch hash mismatch")
        if record.get("sos_patch_hash")!=patch_hash("sos",patchset): raise ValueError("Qualification SOS patch hash mismatch")
        return record
    raise ValueError("Successful CI workflow exists, but no exact qualification artifact was found")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--repository",default=os.environ.get("GITHUB_REPOSITORY",""))
    p.add_argument("--custom-sha",required=True)
    p.add_argument("--upstream-sha",required=True)
    p.add_argument("--upstream-ref",required=True)
    p.add_argument("--output",type=Path,default=Path(".work/ci-qualification.json"))
    a=p.parse_args()
    record=verify(a.repository,a.custom_sha,a.upstream_sha,a.upstream_ref)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(record,indent=2)+"\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"],"a") as out:
            out.write(f"patchset={record['patchset']}\n")
            out.write(f"upstream_version={record['upstream_version']}\n")
