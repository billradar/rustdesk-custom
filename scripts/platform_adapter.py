#!/usr/bin/env python3
"""Review-bounded official platform recipes from the exact prepared-source commit."""
import argparse,hashlib,json,os,re
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
JOBS={'linux':'build-rustdesk-linux','macos':'build-for-macOS','android':'build-rustdesk-android','ios':'build-rustdesk-ios','windows':'build-for-windows-flutter','web':'build-rustdesk-web'}
FILES=['build.py','build.rs','Cargo.toml','flutter/pubspec.yaml','.github/workflows/bridge.yml']
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def inspect(tree,platform,arch):
 tree=Path(tree);d=yaml.safe_load((tree/'.github/workflows/flutter-build.yml').read_text());job=d['jobs'][JOBS[platform]]
 env={k:str(v) for k,v in d['env'].items() if 'secrets.' not in str(v) and 'inputs.' not in str(v)}
 rows=job.get('strategy',{}).get('matrix',{}).get('job',[{'arch':'web','os':job.get('runs-on')}]);row=next((r for r in rows if r.get('arch')==arch),None)
 if row is None:raise ValueError('BUILD_COMPAT: official architecture not present')
 runner=row.get('os') or row.get('on') or row.get(True)
 # YAML 1.1 parses the official matrix field "on" as boolean True. Normalize keys.
 normalized=json.loads(json.dumps(job));identity={'job':normalized,'env':env,'files':{}}
 for p in FILES:
  identity['files'][p]=hashlib.sha256((tree/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
 if platform=='android':
  for p in ['flutter/build_android_deps.sh','flutter/ndk_arm64.sh','flutter/ndk_arm.sh','flutter/ndk_x64.sh','flutter/android/app/build.gradle']:
   identity['files'][p]=hashlib.sha256((tree/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
 result={'platform':platform,'architecture':arch,'runner':runner,'target':row.get('target'),'triplet':row.get('vcpkg-triplet'),'official_matrix':row,'signature':digest(identity),'rust':env.get('MAC_RUST_VERSION') if platform=='macos' else env['RUST_VERSION'],'flutter':env.get('ANDROID_FLUTTER_VERSION') if platform=='android' else env['FLUTTER_VERSION'],'vcpkg':env['VCPKG_COMMIT_ID'],'ndk':env.get('NDK_VERSION'),'cargo_ndk':env.get('CARGO_NDK_VERSION'),'cmake':env.get('VCPKG_CMAKE_VERSION',''),'official_disabled':job.get('if') is False,'tools':env}
 return result,job

def check(tree,platform,arch):
 p,j=inspect(tree,platform,arch);known=json.loads((ROOT/'metadata/platform-adapter-profiles.json').read_text())
 if p['signature'] not in known['approved'].get(platform,[]):raise ValueError('BUILD_COMPAT: unreviewed official '+platform+' build interface')
 if p['official_disabled']:raise ValueError('BUILD_COMPAT: official job is disabled')
 return p,j

def render(text,profile):
 row=profile['official_matrix'];env=dict(profile['tools'],RUST_TOOLCHAIN_VERSION=profile['rust']+'.0' if profile['rust'].count('.')==1 else profile['rust'])
 def replace(m):
  key=m.group(1).strip()
  if key.startswith('matrix.job.'):
   v=row.get(key[11:])
  elif key.startswith('env.'):v=env.get(key[4:])
  elif key=='github.workspace':v='/workspace'
  else:raise ValueError('BUILD_COMPAT: unhandled official expression '+key)
  if v is None:raise ValueError('BUILD_COMPAT: missing official expression '+key)
  return str(v)
 s=re.sub(r'\$\{\{\s*(.*?)\s*\}\}',replace,text)
 if '${{' in s:raise ValueError('BUILD_COMPAT: unresolved recipe expression')
 return s

def linux_scripts(tree,arch,out):
 p,j=check(tree,'linux',arch);s=next(s for s in j['steps'] if s.get('name')=='Build rustdesk' and 'with' in s);out.mkdir(parents=True,exist_ok=True)
 (out/'install.sh').write_text('set -euo pipefail\n'+render(s['with']['install'],p))
 (out/'build.sh').write_text('set -euo pipefail\ncd /workspace\n'+render(s['with']['run'],p)+'\ncd /workspace\npython3 /custom/scripts/native_config_probe.py --verify-library /workspace/target/release/liblibrustdesk.so\n')
 return p
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('tree',type=Path);a.add_argument('--platform',required=True,choices=JOBS);a.add_argument('--arch',required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--linux-scripts',type=Path);a=a.parse_args()
 p,j=check(a.tree,a.platform,a.arch)
 if a.linux_scripts:linux_scripts(a.tree,a.arch,a.linux_scripts)
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(p,indent=2)+'\n')
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:
   for k in ['runner','rust','flutter','vcpkg','target','triplet','ndk','cargo_ndk','cmake']:f.write(k+'='+str(p.get(k) or '')+'\n')
 print('Reviewed platform build interface: PASS')
