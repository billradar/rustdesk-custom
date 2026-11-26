"""Exact-source macOS ARM64 v4 fixture recipe; never a release approval.

The production macos_arm64 policy and receipt format are deliberately unchanged.
Only reviewed exact upstream commits may use the candidate Flutter 3.44 recipe.
The real-package fixture worker remains pinned to SOURCE.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml

from scripts.build import build_adapter, macos_arm64 as stable
from scripts.platform import platform_adapter as adapter

SOURCE = '51f94394ce61e1f3d26229565c326b2862cbdd1f'
# a0c0963c changes PR files; 45e34a69 changes Italian translation only.
# The exact build recipe blobs are unchanged; fixture workers remain pinned.
REVIEWED_SOURCES = frozenset((SOURCE, 'a0c0963c483fc8f1aeed4547787d1673adcb583c', '45e34a69239c2c2467fd02af8ee97263ff26ef23'))
PLATFORM_SIGNATURE = '4ce88d3e563be3c68b19dd2286cc053304774d6aab74b4373ad56fa4056ec433'
BRIDGE_SIGNATURE = '1af2302002908d0bbc7e7d3f6cc3ba20db6de1edd4d2ecd733e470c1dabb4741'
# Git object identities observed directly at the frozen official commit.
PINNED_BLOBS = {
    '.github/workflows/flutter-build.yml': '9f891b54b820f6cbf57e2cb6749cbd2bb8574694',
    '.github/workflows/bridge.yml': '940e1a332f1eadfdf70b5073deb9e6c3ced71410',
    stable.bridge_recipe.PATCH: 'ab82b4ee40e49cd7e81d527150ce72f495388160',
}
TRANSFORMS = tuple(stable.TRANSFORMS) + ('flutter/lib/common/widgets/dialog.dart',)
BRIDGE_FILES = tuple(stable.BRIDGE_FILES)
INPUTS = TRANSFORMS + BRIDGE_FILES
PROTECTED = tuple(sorted((set(adapter.FILES) | set(PINNED_BLOBS)) - set(INPUTS)))
RECEIPT = 'macos-arm64-ci-transform.json'
BRIDGE_INFO = 'macos-arm64-ci-bridge-info.json'
TOOLS = {'runner':'macos-26', 'upstream_runner':'macos-26',
         'target':'aarch64-apple-darwin','triplet':'arm64-osx',
         'rust':'1.81','flutter':'3.44.9',
         'vcpkg':'9e593bb18ea69cc5095e012465dcd675a822ed0d'}
BRIDGE_TOOLS = {'bridge_flutter':'3.44.8','bridge_rust':'1.75',
                'cargo_expand':'1.0.95','frb':'1.80.1'}

def require(ok, message):
    if not ok:
        raise ValueError('BUILD_COMPAT: Mac ARM CI '+message)

def source_sha(tree):
    return subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD'],text=True).strip()

def sha(path):
    return stable.sha(path)

def blob(path):
    raw=Path(path).read_bytes()
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def context(tree, *, worker=False):
    require(os.environ.get('BUILD_CHANNEL')=='ci' and
            os.environ.get('BUILD_CONFIGURATION')=='TEST ONLY' and
            os.environ.get('PATCHSET')=='v4' and
            os.environ.get('GITHUB_ACTIONS')=='true' and
            os.environ.get('GITHUB_EVENT_NAME') in ('pull_request','workflow_dispatch') and
            not os.environ.get('BUILD_FLAVOR') and
            os.environ.get('UPSTREAM_EXPECTED_SHA')==SOURCE and source_sha(tree)==SOURCE,
            'fixture context or source mismatch')
    if worker:
        require(Path(tree).resolve()==Path('.work/native/source').resolve() and
                os.environ.get('PLATFORM')=='macos' and os.environ.get('PLATFORM_ARCH')=='aarch64' and
                os.environ.get('VARIANT') in ('standard','sos') and
                os.environ.get('EXPECTED_RUNNER')=='macos-26' and
                os.environ.get('RUSTDESK_ID_SERVER')=='test.invalid',
                'isolated native worker required')
    else:
        require(Path(tree).resolve()==Path('.work/mac-arm-ci-bridge').resolve(),
                'isolated bridge generator required')

def check_profile(tree, p, *, original_tree=None):
    """Check both existing candidate registries and the exact dedicated recipe."""
    tree=Path(tree); recipe=Path(original_tree) if original_tree is not None else tree
    actual=source_sha(tree)
    require(actual in REVIEWED_SOURCES and p.get('candidate_source_sha')==actual and
            p.get('ci_candidate_only') is True and p.get('stable_allowed') is False and
            p.get('platform')=='macos' and p.get('architecture')=='aarch64' and
            p.get('signature')==PLATFORM_SIGNATURE and
            all(p.get(k)==v for k,v in TOOLS.items()), 'unknown candidate platform identity')
    require(all(blob(recipe/n)==v for n,v in PINNED_BLOBS.items()), 'official workflow/helper bytes changed')
    b,_=build_adapter.inspect(recipe)
    require(b['signature']==BRIDGE_SIGNATURE, 'unknown common bridge interface')
    row=build_adapter._ci_candidate(tree,b)
    require(row['source_sha']==actual, 'bridge candidate source mismatch')
    workflow=yaml.safe_load((recipe/'.github/workflows/bridge.yml').read_text())
    dedicated=[r for r in workflow['jobs']['generate_bridge']['strategy']['matrix']['job']
               if r['artifact-name']=='bridge-artifact-flutter-3.44']
    require(len(dedicated)==1 and dedicated[0]['os']=='ubuntu-22.04' and
            dedicated[0]['target']=='x86_64-unknown-linux-gnu', 'unknown dedicated bridge matrix')
    tools={'bridge_flutter':str(dedicated[0]['flutter-version']),
           'bridge_rust':str(workflow['env']['RUST_VERSION']),
           'cargo_expand':str(workflow['env']['CARGO_EXPAND_VERSION']),
           'frb':str(workflow['env']['FLUTTER_RUST_BRIDGE_VERSION'])}
    require(tools==BRIDGE_TOOLS, 'dedicated bridge tools changed')
    return dict(p,macos_flutter344=True,bridge_signature=b['signature'],
                patch_sha256=sha(recipe/stable.bridge_recipe.PATCH),
                source_workflow_sha256=sha(recipe/'.github/workflows/flutter-build.yml'),
                **tools)

def profile(tree):
    return adapter.check(tree,'macos','aarch64',channel='ci')[0]

def original(tree, *, reviewed_source=False):
    """Reconstruct untransformed recipe from the worker's immutable Git HEAD."""
    tree=Path(tree)
    actual=source_sha(tree)
    require(actual in REVIEWED_SOURCES if reviewed_source else actual==SOURCE,'source HEAD changed')
    names=set(adapter.FILES+build_adapter.CRITICAL_FILES)|set(PINNED_BLOBS)
    with tempfile.TemporaryDirectory(prefix='mac-arm-ci-recipe-') as tmp:
        root=Path(tmp)
        for name in names:
            dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(subprocess.check_output(['git','-C',str(tree),'show','HEAD:'+name]))
        p,job=adapter.inspect(root,'macos','aarch64')
        p=adapter._ci_platform_candidate(tree,p,'macos','aarch64')
        return check_profile(tree,p,original_tree=root),job

def inventory(tree, names):
    return {name:sha(Path(tree)/name) for name in names}

def bridge_info(tree):
    tree=Path(tree);context(tree)
    p,_=original(tree)
    info={'upstream_sha':SOURCE,'custom_sha':os.environ['GITHUB_SHA'],
          'workflow_run':os.environ['GITHUB_RUN_ID'],'flutter':p['bridge_flutter'],
          'patch_sha256':p['patch_sha256'],'files':inventory(tree,BRIDGE_FILES)}
    (tree/BRIDGE_INFO).write_text(json.dumps(info,sort_keys=True,indent=2)+'\n')

def validate_bridge(info,p):
    expected={'upstream_sha':SOURCE,'custom_sha':os.environ['GITHUB_SHA'],
              'workflow_run':os.environ['GITHUB_RUN_ID'],'flutter':p['bridge_flutter'],
              'patch_sha256':p['patch_sha256']}
    require(set(info)==set(expected)|{'files'} and all(info.get(k)==v for k,v in expected.items())
            and set(info['files'])==set(BRIDGE_FILES),'bridge identity/inventory mismatch')

def transform(tree, bridge):
    tree,bridge=Path(tree),Path(bridge);context(tree,worker=True)
    require(not (tree/RECEIPT).exists() and not (tree/stable.RECEIPT).exists(),
            'existing transformation receipt')
    p=profile(tree);expected,_=original(tree)
    require(p==expected,'prepared candidate recipe differs from upstream')
    stable.verify_sdk(p)
    require(not bridge.is_symlink(),'symlinked bridge')
    names={f.relative_to(bridge).as_posix() for f in bridge.rglob('*') if f.is_file() or f.is_symlink()}
    require(names==set(BRIDGE_FILES)|{BRIDGE_INFO},'unexpected bridge artifact inventory')
    info=stable.read(bridge/BRIDGE_INFO);validate_bridge(info,p)
    require(inventory(bridge,BRIDGE_FILES)==info['files'],'bridge content digest mismatch')
    before=inventory(tree,INPUTS);protected=inventory(tree,PROTECTED)
    stable.bridge_recipe.apply(tree)
    require(all(sha(tree/n)!=before[n] for n in TRANSFORMS),'incomplete official Flutter 3.44 source transformation')
    require(inventory(tree,PROTECTED)==protected,'official helper modified protected recipe')
    for name in BRIDGE_FILES:
        shutil.copy2(bridge/name,tree/name)
    receipt={'schema':'macos-arm64-ci-transform-v1','release_eligible':False,
             'profile':p,'variant':os.environ['VARIANT'],'bridge':info,
             'before':before,'after':inventory(tree,INPUTS),'protected':protected}
    (tree/RECEIPT).write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    verified(tree)

def verified(tree, *, post_build=False):
    tree=Path(tree);context(tree,worker=True)
    r=stable.read(tree/RECEIPT)
    p,job=original(tree)
    require(set(r)=={'schema','release_eligible','profile','variant','bridge','before','after','protected'}
            and r['schema']=='macos-arm64-ci-transform-v1' and r['release_eligible'] is False
            and r['profile']==p and r['variant']==os.environ['VARIANT'],
            'receipt purpose or source identity mismatch')
    validate_bridge(r['bridge'],p)
    require(set(r['before'])==set(INPUTS) and set(r['after'])==set(INPUTS) and
            set(r['protected'])==set(PROTECTED),'receipt inventory mismatch')
    require(all(r['before'][n]!=r['after'][n] for n in TRANSFORMS),'incomplete source transformation')
    require(all(r['after'][n]==r['bridge']['files'][n] for n in BRIDGE_FILES),'bridge receipt mismatch')
    require(inventory(tree,INPUTS)==r['after'],'transformed source drift')
    require(all(stable.protected_digest(tree,n,post_build=post_build)==r['protected'][n]
                for n in PROTECTED),'protected recipe input drift')
    stable.verify_sdk(p)
    return p,job

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('profile','bridge-info','transform'))
    parser.add_argument('tree',type=Path)
    parser.add_argument('--bridge',type=Path)
    args=parser.parse_args()
    if args.mode=='profile':
        context(args.tree);p=profile(args.tree)
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            for key in BRIDGE_TOOLS:f.write(key+'='+p[key]+'\n')
        print('Dedicated exact-source CI bridge profile: PASS')
    elif args.mode=='bridge-info':
        bridge_info(args.tree)
    else:
        require(args.bridge is not None,'bridge input required')
        transform(args.tree,args.bridge)

if __name__=='__main__':
    main()
