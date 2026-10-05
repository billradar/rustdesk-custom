#!/usr/bin/env python3
"""Redacted diagnostics and explicit failure categories, never ignore build failures."""
import json,os,subprocess,sys
from pathlib import Path
from scripts.signing.production_config import NAMES,scan_bytes
platform=os.environ['PLATFORM'];arch=os.environ['PLATFORM_ARCH'];variant=os.environ['VARIANT']
values=sorted([os.environ[n] for n in NAMES if os.environ.get(n)],key=len,reverse=True)
def redact(text):
    for value in values:text=text.replace(value,'[REDACTED]')
    scan_bytes(text.encode());return text
lines=[];p=subprocess.Popen(['bash','scripts/build-'+platform+'.sh'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
try:
    for line in p.stdout:
        line=redact(line);print(line,end='',flush=True);lines.append(line);lines=lines[-100:]
except BaseException:
    p.terminate();p.wait();raise
code=p.wait();reason=''.join(lines)
categories=['PATCH_COMPAT','BUILD_COMPAT','TOOLCHAIN','DEPENDENCY','PLATFORM_API','ARCH','PACKAGE','SIGNING','PROVENANCE','INFRASTRUCTURE']
category=next((c for c in categories if c+':' in reason),'UNKNOWN')
report={'target':platform+'-'+arch+'-'+variant,'result':'PASS' if code==0 else 'FAIL','exit_code':code,'failure_category':None if code==0 else category,'workflow_run':os.environ['GITHUB_RUN_ID'],'job':os.environ['GITHUB_JOB'],'upstream_sha':os.environ['UPSTREAM_EXPECTED_SHA'],'patchset':os.environ['PATCHSET'],'diagnostic_tail':lines if code else []}
out=Path('.work/target-diagnostic');out.mkdir(parents=True,exist_ok=True);(out/'diagnostic.json').write_text(json.dumps(report,indent=2)+'\n')
sys.exit(code)
