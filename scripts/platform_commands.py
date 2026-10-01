#!/usr/bin/env python3
"""Execute named commands only after reviewing the exact upstream job signature."""
import subprocess,sys
from pathlib import Path
from platform_adapter import check,render
root,platform,arch,phase=sys.argv[1:];root=Path(root).resolve();profile,job=check(root,platform,arch)
names={('macos','setup'):['Install build runtime','Install NASM','Patch flutter','Workaround for flutter issue'],('macos','build'):['Build rustdesk'],('android','deps'):['Install vcpkg dependencies'],('android','native'):['Build rustdesk lib'],('android','package'):['Build rustdesk']}
for name in names[(platform,phase)]:
 s=next(s for s in job['steps'] if s.get('name')==name)
 script=render(s['run'],profile).replace('/workspace',str(root))
 if platform=='macos':
  # Official GNU sed spelling cannot be used with BSD sed on hosted macOS.
  script=script.replace('sed -i -e','sed -i \'\' -e')
 subprocess.run(['bash','-euo','pipefail','-c',script],cwd=root,check=True)
