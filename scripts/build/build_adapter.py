#!/usr/bin/env python3
"""Reviewed exact-source build profiles. Unknown critical definitions fail closed."""
import argparse, hashlib, json, os, re
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[2]
CRITICAL_FILES = ['build.py', 'build.rs', '.github/workflows/bridge.yml',
                  '.github/workflows/third-party-RustDeskTempTopMostWindow.yml',
                  '.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff']
TOOLS = ['RUST_VERSION', 'FLUTTER_VERSION', 'LLVM_VERSION', 'VCPKG_COMMIT_ID']

def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def inspect(tree):
    tree=Path(tree)
    build=yaml.safe_load((tree/'.github/workflows/flutter-build.yml').read_text())
    env=build['env']; job=build['jobs']['build-for-windows-flutter']
    rows=job['strategy']['matrix']['job']
    x64=next(r for r in rows if r['target']=='x86_64-pc-windows-msvc')
    runner=x64.get('os', x64.get('runner'))
    # The official matrix calls its runner field "os" or "on" across snapshots.
    runner=runner or x64.get('on') or x64.get(True)
    if runner!='windows-2022': raise ValueError('Unsupported official Windows x64 runner')
    critical={'windows_job':job,'tools':{k:env[k] for k in TOOLS},'files':{}}
    for p in CRITICAL_FILES:
        critical['files'][p]=hashlib.sha256((tree/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    version=re.search(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+(?:[-+][\w.-]+)?)"',
                      (tree/'Cargo.toml').read_text(),re.M)
    if not version: raise ValueError('Upstream source version missing')
    bridge=yaml.safe_load((tree/'.github/workflows/bridge.yml').read_text())
    b_env=bridge['env']
    bridge_profile=next(r for r in bridge['jobs']['generate_bridge']['strategy']['matrix']['job'] if r['artifact-name']=='bridge-artifact')
    helper=re.search(r'git checkout\s+([0-9a-f]{40})',(tree/'.github/workflows/third-party-RustDeskTempTopMostWindow.yml').read_text())
    if not helper: raise ValueError('Official helper pin missing')
    profile={'signature':digest(critical),'upstream_version':version.group(1),
             'runner':runner,'rust':str(env['RUST_VERSION']), 'flutter':str(env['FLUTTER_VERSION']),
             'llvm':str(env['LLVM_VERSION']), 'vcpkg':env['VCPKG_COMMIT_ID'],
             'bridge_rust':str(b_env['RUST_VERSION']), 'cargo_expand':str(b_env['CARGO_EXPAND_VERSION']),
             'frb':str(b_env['FLUTTER_RUST_BRIDGE_VERSION']), 'bridge_flutter':str(bridge_profile['flutter-version']),
             'helper_commit':helper.group(1),
             'source_sbom_requested':'generate-sbom' in build['jobs']}
    return profile, critical

def check(tree):
    profile,critical=inspect(tree)
    known=json.loads((ROOT/'metadata/build-adapter-profiles.json').read_text())
    approved=next((p for p in known['profiles'] if p['signature']==profile['signature']),None)
    if approved is None: raise ValueError('BUILD_COMPATIBILITY=FAIL: unknown critical official Windows/bridge/build interface; review in staging')
    profile['reviewed_profile']=approved['id']; profile['Build Compatibility']='PASS'
    return profile

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('tree',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    try: result=check(args.tree)
    except Exception as e:
        args.output.write_text(json.dumps({'Build Compatibility':'FAIL','reason':str(e)},indent=2)+'\n');raise
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            for k,v in result.items():
                if isinstance(v,(str,int,bool)) and re.fullmatch(r'[A-Za-z_]+',k): f.write(f'{k}={str(v).lower() if isinstance(v,bool) else v}\n')
