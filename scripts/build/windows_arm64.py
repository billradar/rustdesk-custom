#!/usr/bin/env python3
"""Native Windows ARM64 recipe and exact-source Flutter 3.44 bridge gates."""
import argparse, hashlib, json, os, shutil, struct, subprocess, sys
from pathlib import Path
import yaml
from scripts.build.build_adapter import check as baseline
ROOT = Path(__file__).resolve().parents[2]
PATCH = '.github/patches/apply_flutter_3.44_source_patches.sh'
BRIDGE_FILES = ['src/bridge_generated.rs', 'src/bridge_generated.io.rs',
 'flutter/lib/generated_bridge.dart', 'flutter/lib/generated_bridge.freezed.dart',
 'flutter/macos/Runner/bridge_generated.h', 'flutter/ios/Runner/bridge_generated.h']
TRANSFORMS = ['flutter/lib/common.dart', 'flutter/pubspec.yaml']
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def inspect(tree):
    tree = Path(tree); p = baseline(tree)
    workflow = yaml.safe_load((tree/'.github/workflows/flutter-build.yml').read_text())
    row = next(r for r in workflow['jobs']['build-for-windows-flutter']['strategy']['matrix']['job'] if r['arch']=='aarch64')
    bridge = yaml.safe_load((tree/'.github/workflows/bridge.yml').read_text())
    b = next(r for r in bridge['jobs']['generate_bridge']['strategy']['matrix']['job'] if r['artifact-name']=='bridge-artifact-flutter-3.44')
    p.update(runner=row.get('os') or row.get('on') or row.get(True), target=row['target'], triplet=row['vcpkg-triplet'],
             flutter=str(workflow['env']['FLUTTER_WINDOWS_ARM_VERSION']), bridge_flutter=str(b['flutter-version']),
             patch_sha256=sha(tree/PATCH), architecture='aarch64')
    identity = {k:p[k] for k in ('signature','runner','target','triplet','flutter','bridge_flutter','patch_sha256')}
    return p, identity

def check(tree):
    p, identity = inspect(tree)
    approved = json.loads((ROOT/'metadata/build/windows-arm64-policy.json').read_text())['profiles']
    if identity not in approved: raise ValueError('Unreviewed Windows ARM64/Flutter 3.44 recipe')
    if p['runner']!='windows-11-arm' or p['target']!='aarch64-pc-windows-msvc' or p['triplet']!='arm64-windows-static':
        raise ValueError('Native Windows ARM64 recipe required')
    return p

def pe(path, arch='aarch64'):
    b=Path(path).read_bytes(); machine={'aarch64':0xaa64,'x86_64':0x8664}[arch]
    if len(b)<64 or b[:2]!=b'MZ': raise ValueError('Missing PE header: '+Path(path).name)
    off=struct.unpack_from('<I',b,0x3c)[0]
    if off+6>len(b) or b[off:off+4]!=b'PE\0\0' or struct.unpack_from('<H',b,off+4)[0]!=machine:
        raise ValueError('Wrong Windows '+arch+' machine: '+Path(path).name)

def apply(tree):
    subprocess.run(['bash',PATCH],cwd=tree,check=True)

def bridge_info(tree):
    p=check(tree)
    info={'upstream_sha':subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD'],text=True).strip(),
          'custom_sha':os.environ['GITHUB_SHA'],'workflow_run':os.environ['GITHUB_RUN_ID'],
          'flutter':p['bridge_flutter'],'patch_sha256':p['patch_sha256'],
          'files':{n:sha(tree/n) for n in BRIDGE_FILES}}
    if info['upstream_sha']!=os.environ['UPSTREAM_EXPECTED_SHA']: raise ValueError('ARM bridge source mismatch')
    (tree/'arm64-bridge-info.json').write_text(json.dumps(info,indent=2)+'\n')

def transform(tree,bridge):
    p=check(tree); manifest=json.loads((tree/'source-manifest.json').read_text())
    info=json.loads((bridge/'arm64-bridge-info.json').read_text())
    for k,v in {'upstream_sha':manifest['upstream_sha'],'custom_sha':os.environ['GITHUB_SHA'],
                'workflow_run':os.environ['GITHUB_RUN_ID'],'flutter':p['bridge_flutter'],'patch_sha256':p['patch_sha256']}.items():
        if info.get(k)!=v: raise ValueError('ARM bridge identity mismatch: '+k)
    if set(info['files'])!=set(BRIDGE_FILES): raise ValueError('Incomplete ARM bridge inventory')
    before={n:sha(tree/n) for n in TRANSFORMS+BRIDGE_FILES}
    if any(before[n]!=manifest['files'][n] for n in before): raise ValueError('ARM transformation input drift')
    apply(tree)
    for n in BRIDGE_FILES:
        if sha(bridge/n)!=info['files'][n]: raise ValueError('ARM bridge digest mismatch')
        shutil.copy2(bridge/n,tree/n)
    receipt={'profile':p,'upstream_sha':manifest['upstream_sha'],'source_manifest_sha256':sha(tree/'source-manifest.json'),
             'bridge':info,'before':before,'after':{n:sha(tree/n) for n in before}}
    (tree/'windows-arm64-transform.json').write_text(json.dumps(receipt,indent=2)+'\n')

def verify_transform(tree):
    p=check(tree); r=json.loads((tree/'windows-arm64-transform.json').read_text())
    manifest=json.loads((tree/'source-manifest.json').read_text())
    if r['profile']!=p or r['source_manifest_sha256']!=sha(tree/'source-manifest.json') or r['upstream_sha']!=manifest['upstream_sha']:
        raise ValueError('ARM source transformation provenance mismatch')
    names=set(TRANSFORMS+BRIDGE_FILES)
    if set(r['before'])!=names or set(r['after'])!=names: raise ValueError('ARM transform inventory mismatch')
    for n in names:
        if r['before'][n]!=manifest['files'][n] or r['after'][n]!=sha(tree/n): raise ValueError('ARM transformed source drift: '+n)
    for n in BRIDGE_FILES:
        if r['after'][n]!=r['bridge']['files'][n]: raise ValueError('ARM bridge/source mismatch')
    return p

def validate_receipt(folder, info):
    """Revalidate the ARM build's immutable transformation evidence at fan-in."""
    r=json.loads((folder/'windows-arm64-transform.json').read_text())
    m=json.loads((folder/'source-manifest.json').read_text())
    if r['source_manifest_sha256']!=sha(folder/'source-manifest.json') or r['upstream_sha']!=info['upstream_sha']:
        raise ValueError('ARM package/source receipt mismatch')
    identity={k:r['profile'][k] for k in ('signature','runner','target','triplet','flutter','bridge_flutter','patch_sha256')}
    approved=json.loads((ROOT/'metadata/build/windows-arm64-policy.json').read_text())['profiles']
    if identity not in approved: raise ValueError('Unreviewed packaged ARM recipe')
    for k,v in {'upstream_sha':info['upstream_sha'],'custom_sha':info['custom_repository_sha'],
                'workflow_run':str(info['workflow_run']),'flutter':r['profile']['bridge_flutter'],
                'patch_sha256':r['profile']['patch_sha256']}.items():
        if r['bridge'].get(k)!=v: raise ValueError('ARM package bridge provenance mismatch: '+k)
    if set(r['before'])!=set(TRANSFORMS+BRIDGE_FILES) or set(r['after'])!=set(r['before']):
        raise ValueError('ARM package transformation inventory mismatch')
    for n in r['before']:
        if r['before'][n]!=m['files'][n]: raise ValueError('ARM package transformation source mismatch')
    for n in BRIDGE_FILES:
        if r['after'][n]!=r['bridge']['files'][n]: raise ValueError('ARM package bridge checksum mismatch')
    if info.get('engine_library_sha256')!=sha(folder/'rustdesk/flutter_windows.dll'):
        raise ValueError('ARM native engine checksum mismatch')

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['profile','bridge-info','transform','verify']);a.add_argument('tree',type=Path);a.add_argument('--bridge',type=Path);a=a.parse_args()
    if a.mode=='bridge-info': bridge_info(a.tree)
    elif a.mode=='transform': transform(a.tree,a.bridge)
    elif a.mode=='verify': verify_transform(a.tree)
    else:
        p=check(a.tree)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:
                for k,v in p.items():
                    if isinstance(v,(str,int)): f.write(f'{k}={v}\n')
        print('Reviewed native Windows ARM64 recipe: PASS')
