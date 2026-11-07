"""Exact-source macOS ARM64 Flutter 3.44 bridge and transformation receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from scripts.build import windows_arm64 as bridge_recipe

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT/'metadata/build/macos-arm64-policy.json'
RECEIPT = 'macos-arm64-transform.json'
BRIDGE_INFO = 'macos-arm64-bridge-info.json'
BRIDGE_FILES = bridge_recipe.BRIDGE_FILES
TRANSFORMS = bridge_recipe.TRANSFORMS
INPUTS = TRANSFORMS + BRIDGE_FILES
POLICY_KEYS = ('signature','runner','upstream_runner','target','triplet','rust','flutter','vcpkg',
               'bridge_signature','bridge_flutter','bridge_rust','cargo_expand','frb','patch_sha256','source_workflow_sha256')
# Exact substitutions in the already reviewed official Mac ARM build step.
# These are checked only after compilation; all remaining bytes must still
# hash to the immutable prepared inventory. Never ignore whole recipe files.
DEPLOYMENT_EDITS = {
    'build.py': (b'MACOSX_DEPLOYMENT_TARGET=10.14', b'MACOSX_DEPLOYMENT_TARGET=12.3'),
    'Cargo.toml': (b'osx_minimum_system_version = "10.14"', b'osx_minimum_system_version = "12.3"'),
}


def require(value, message):
    if not value:
        raise ValueError('BUILD_COMPAT: '+message)


def sha(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(), 'Nonregular Mac ARM input: '+path.name)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=(16 if path.name=='source-manifest.json' else 2)*1024*1024,
            'Missing/oversized Mac ARM receipt')
    return json.loads(path.read_bytes())


def policy():
    value=read(POLICY)
    require(set(value)=={'schema_version','profiles'} and type(value['schema_version']) is int
            and value['schema_version']==1 and type(value['profiles']) is list and value['profiles']
            and all(set(p)==set(POLICY_KEYS) and all(type(v) is str and v for v in p.values())
                    for p in value['profiles']), 'Unknown Mac ARM policy schema')
    return value


def approved(profile):
    identity={key:profile[key] for key in POLICY_KEYS}
    require(identity in policy()['profiles'], 'Unreviewed macOS ARM64/Flutter 3.44 recipe')
    require(profile.get('platform')=='macos' and profile.get('architecture')=='aarch64'
            and profile.get('macos_flutter344') is True, 'Wrong Mac ARM recipe purpose')
    return profile


def check_profile(tree, profile):
    # Reuse the already reviewed official Linux bridge generator policy, never
    # a Windows binary or Windows package transformation receipt.
    bridge=bridge_recipe.check(tree)
    profile=dict(profile,macos_flutter344=True,bridge_signature=bridge['signature'],
                 source_workflow_sha256=sha(Path(tree)/'.github/workflows/flutter-build.yml'),
                 **{k:bridge[k] for k in ('bridge_flutter','bridge_rust','cargo_expand','frb','patch_sha256')})
    return approved(profile)


def profile(tree):
    from scripts.platform.platform_adapter import check
    return check(tree,'macos','aarch64')[0]


def original(tree):
    """Reconstruct only reviewed recipe inputs from this tree's exact Git HEAD.

    pubspec is deliberately transformed on the worker. Its modified bytes may
    never be used to silently select a different approved recipe.
    """
    from scripts.platform.platform_adapter import FILES, check
    from scripts.build.build_adapter import CRITICAL_FILES
    tree=Path(tree)
    actual=subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD'],text=True).strip()
    require(actual==os.environ['UPSTREAM_EXPECTED_SHA'], 'Mac ARM Git source drift')
    paths=set(FILES+CRITICAL_FILES+['.github/workflows/flutter-build.yml',bridge_recipe.PATCH])
    with tempfile.TemporaryDirectory(prefix='macos-arm64-recipe-') as tmp:
        root=Path(tmp)
        for name in sorted(paths):
            raw=subprocess.check_output(['git','-C',str(tree),'show','HEAD:'+name])
            dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        result=check(root,'macos','aarch64')
    require(result[0].get('macos_flutter344') is True, 'Legacy source cannot acquire a Mac ARM receipt')
    return result


def verify_sdk(profile):
    require(os.environ.get('RUNNER_OS')=='macOS' and os.environ.get('RUNNER_ARCH')=='ARM64',
            'Native Mac ARM runner required')
    sdk=json.loads(subprocess.check_output(['flutter','--version','--machine'],text=True))
    require(sdk.get('frameworkVersion')==profile['flutter'], 'Mac ARM Flutter SDK mismatch')


def bridge_info(tree):
    p,_=original(tree)
    bridge_recipe.bridge_info(tree)
    src=Path(tree)/'arm64-bridge-info.json';info=read(src)
    require(info['flutter']==p['bridge_flutter'] and info['patch_sha256']==p['patch_sha256'],
            'Mac bridge generator recipe mismatch')
    src.rename(Path(tree)/BRIDGE_INFO)


def verify_bridge(info, p, manifest):
    require(set(info)=={'upstream_sha','custom_sha','workflow_run','flutter','patch_sha256','files'},
            'Unknown Mac bridge schema')
    for key,value in {'upstream_sha':manifest['upstream_sha'],
                      'custom_sha':manifest['custom_repository_sha'],
                      'workflow_run':str(manifest['prepare_workflow_run']),
                      'flutter':p['bridge_flutter'],'patch_sha256':p['patch_sha256']}.items():
        require(info.get(key)==value, 'Mac bridge provenance mismatch: '+key)
    require(set(info['files'])==set(BRIDGE_FILES), 'Incomplete Mac bridge inventory')


def transform(tree, bridge):
    tree,bridge=Path(tree),Path(bridge);p=profile(tree);approved(p);verify_sdk(p)
    require(not (tree/RECEIPT).exists(), 'Mac source was already transformed')
    require(not bridge.is_symlink(), 'Symlinked Mac bridge directory')
    inventory={p.relative_to(bridge).as_posix() for p in bridge.rglob('*') if p.is_file() or p.is_symlink()}
    require(inventory==set(BRIDGE_FILES)|{BRIDGE_INFO}, 'Unexpected Mac bridge artifact inventory')
    manifest=read(tree/'source-manifest.json');info=read(bridge/BRIDGE_INFO)
    require(manifest['upstream_sha']==os.environ['UPSTREAM_EXPECTED_SHA']
            and manifest['custom_repository_sha']==os.environ['GITHUB_SHA']
            and str(manifest['prepare_workflow_run'])==os.environ['GITHUB_RUN_ID']
            and manifest['variant'] in ('standard','sos'), 'Mac transformation source context mismatch')
    verify_bridge(info,p,manifest)
    before={name:sha(tree/name) for name in INPUTS}
    require(all(before[n]==manifest['files'].get(n) for n in INPUTS), 'Mac transformation input drift')
    require(all(sha(bridge/n)==info['files'][n] for n in BRIDGE_FILES), 'Mac bridge content drift')
    bridge_recipe.apply(tree)
    for name in BRIDGE_FILES:
        shutil.copy2(bridge/name,tree/name)
    receipt={'schema_version':1,'profile':p,'upstream_sha':manifest['upstream_sha'],
             'variant':manifest['variant'],'source_manifest_sha256':sha(tree/'source-manifest.json'),
             'bridge':info,'before':before,'after':{name:sha(tree/name) for name in INPUTS}}
    (tree/RECEIPT).write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    verified(tree)


def receipt_checks(receipt, manifest, manifest_sha):
    require(set(receipt)=={'schema_version','profile','upstream_sha','variant',
                          'source_manifest_sha256','bridge','before','after'}
            and type(receipt['schema_version']) is int and receipt['schema_version']==1,
            'Unknown Mac transformation schema')
    p=approved(receipt['profile'])
    require(receipt['source_manifest_sha256']==manifest_sha
            and receipt['upstream_sha']==manifest['upstream_sha']
            and receipt['variant']==manifest['variant'], 'Mac source receipt identity mismatch')
    require(set(receipt['before'])==set(INPUTS) and set(receipt['after'])==set(INPUTS),
            'Mac transformation inventory mismatch')
    require(all(receipt['before'][n]==manifest['files'].get(n) for n in INPUTS),
            'Mac transformation before-state mismatch')
    verify_bridge(receipt['bridge'],p,manifest)
    require(all(receipt['after'][n]==receipt['bridge']['files'][n] for n in BRIDGE_FILES),
            'Mac transformed bridge mismatch')
    return p


def protected_digest(tree, name, *, post_build=False):
    path=Path(tree)/name;digest=sha(path)
    if post_build and name in DEPLOYMENT_EDITS:
        before,after=DEPLOYMENT_EDITS[name];raw=path.read_bytes()
        require(raw.count(after)==1, 'Mac protected recipe deployment target drift: '+name)
        digest=hashlib.sha256(raw.replace(after,before)).hexdigest()
    return digest


def verified(tree, *, post_build=False):
    tree=Path(tree);receipt=read(tree/RECEIPT);manifest=read(tree/'source-manifest.json')
    p=receipt_checks(receipt,manifest,sha(tree/'source-manifest.json'))
    require(manifest['upstream_sha']==os.environ['UPSTREAM_EXPECTED_SHA']
            and manifest['custom_repository_sha']==os.environ['GITHUB_SHA']
            and str(manifest['prepare_workflow_run'])==os.environ['GITHUB_RUN_ID'],
            'Mac receipt belongs to another worker context')
    expected,job=original(tree)
    require(p==expected, 'Mac receipt differs from exact official recipe')
    require(all(receipt['after'][n]==sha(tree/n) for n in INPUTS), 'Mac transformed source drift')
    from scripts.platform.platform_adapter import FILES
    for name in set(FILES+['.github/workflows/flutter-build.yml',bridge_recipe.PATCH])-set(INPUTS):
        digest=protected_digest(tree,name,post_build=post_build)
        require(digest==manifest['files'].get(name), 'Mac protected recipe input drift: '+name)
    verify_sdk(p)
    return p,job


def requires_receipt(info, manifest):
    # A worker cannot evade the new gate by clearing its opt-in flag or claiming
    # an older SDK/signature. The immutable prepared workflow bytes also bind it.
    policies=policy()['profiles']
    signature=info.get('platform_adapter_signature',info.get('signature'))
    sdk=info.get('build_toolchain',{}).get('flutter',info.get('flutter',''))
    return (info.get('macos_flutter344') is True or sdk.startswith('3.44.')
            or any(signature==p['signature'] or manifest.get('files',{}).get(
                '.github/workflows/flutter-build.yml')==p['source_workflow_sha256'] for p in policies))


def validate_receipt(folder, info):
    folder=Path(folder);manifest=read(folder/'source-manifest.json')
    p=receipt_checks(read(folder/RECEIPT),manifest,sha(folder/'source-manifest.json'))
    require(info['platform']=='macos' and info['architecture']=='aarch64'
            and info.get('macos_flutter344') is True and info['variant']==manifest['variant']
            and info['upstream_sha']==manifest['upstream_sha']
            and info['custom_repository_sha']==manifest['custom_repository_sha']
            and str(info['workflow_run'])==str(manifest['prepare_workflow_run'])
            and info['prepared_source_identity']==sha(folder/'source-manifest.json')
            and info['platform_adapter_signature']==p['signature'], 'Mac package receipt provenance mismatch')
    require(all(info['build_toolchain'][k]==p[k] for k in ('rust','flutter','vcpkg')),
            'Mac package toolchain mismatch')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('profile','bridge-info','transform'))
    parser.add_argument('tree',type=Path);parser.add_argument('--bridge',type=Path);args=parser.parse_args()
    if args.mode=='bridge-info':bridge_info(args.tree)
    elif args.mode=='transform':
        require(args.bridge is not None,'Mac bridge input required');transform(args.tree,args.bridge)
    else:
        p=profile(args.tree);required=p.get('macos_flutter344') is True
        outputs={'required':str(required).lower()}
        if required:outputs.update({k:p[k] for k in ('flutter','bridge_flutter','bridge_rust','cargo_expand','frb')})
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
                for key,value in outputs.items():stream.write(key+'='+str(value)+'\n')
        print('Reviewed Mac ARM bridge requirement: '+outputs['required'])


if __name__=='__main__':main()
