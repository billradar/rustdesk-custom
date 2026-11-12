#!/usr/bin/env python3
"""Execute named commands only after reviewing the exact upstream job signature."""
import subprocess,sys
from pathlib import Path
from scripts.platform.platform_adapter import check,render
root,platform,arch,phase=sys.argv[1:];root=Path(root).resolve();profile,job=check(root,platform,arch)
names={('macos','setup'):['Install build runtime','Install NASM','Patch flutter','Workaround for flutter issue'],('macos','build'):['Build rustdesk'],('android','deps'):['Install vcpkg dependencies'],('android','native'):['Build rustdesk lib'],('android','package'):['Build rustdesk']}
selected=names[(platform,phase)]
if platform=='android' and phase=='deps' and any(s.get('name')=='Check JNI natives are in ffi.FFI' for s in job['steps']):
 selected=['Check JNI natives are in ffi.FFI']+selected
if platform=='macos' and arch=='aarch64' and phase=='setup' and profile.get('macos_flutter344'):
 selected=[n for n in selected if n!='Patch flutter']
 selected.insert(0,'Keep CocoaPods for Flutter 3.44 (arm64)')
for name in selected:
 s=next(s for s in job['steps'] if s.get('name')==name)
 script=render(s['run'],profile).replace('/workspace',str(root))
 if platform=='macos':
  # Official GNU sed spelling cannot be used with BSD sed on hosted macOS.
  script=script.replace('sed -i -e','sed -i \'\' -e')
 subprocess.run(['bash','-euo','pipefail','-c',script],cwd=root,check=True)
