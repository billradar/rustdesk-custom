#!/usr/bin/env python3
"""Run-bound source artifacts, no credentials/configuration injection during prepare."""
import argparse, datetime, hashlib, json, os, re, shutil, subprocess, tarfile
from pathlib import Path, PurePosixPath
from scripts.upstream.patchsets import patch_hash, verify
from scripts.validation.compatibility import contracts
from scripts.build.build_adapter import check
ROOT=Path(__file__).resolve().parents[2]

def git(tree,*args):return subprocess.check_output(['git','-C',str(tree),*args],text=True).strip()
def run(*args):subprocess.run(list(map(str,args)),check=True)
def inventory(tree):
    result={}
    for p in sorted(tree.rglob('*')):
        relative=p.relative_to(tree)
        if '.git' in relative.parts:continue
        if p.is_symlink():result[relative.as_posix()]={'symlink':os.readlink(p)}
        elif p.is_file():result[relative.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result

def verify_tree(tree,variant,sha,patchset,custom_sha,run_id):
    manifest=json.loads((tree/'source-manifest.json').read_text())
    expected={'variant':variant,'upstream_sha':sha,'patchset':patchset,'custom_repository_sha':custom_sha,
              'prepare_workflow_run':str(run_id),'upstream_repository':'rustdesk/rustdesk'}
    for k,v in expected.items():
        if manifest.get(k)!=v:raise ValueError('Prepared source provenance mismatch: '+k)
    if manifest['common_patch_hash']!=patch_hash('common',patchset):raise ValueError('Common source patch identity mismatch')
    if manifest['sos_patch_hash']!=(patch_hash('sos',patchset) if variant=='sos' else None):raise ValueError('SOS source patch identity mismatch')
    if git(tree,'rev-parse','HEAD')!=sha:raise ValueError('Prepared git source SHA mismatch')
    actual=inventory(tree);actual.pop('source-manifest.json',None)
    if actual!=manifest['files']:raise ValueError('Prepared source file inventory mismatch')
    contracts(tree,variant,patchset);check(tree)
    return manifest

def prepare(base,output,ref,sha,name,bridge):
    verify(name)
    if git(base,'rev-parse','HEAD')!=sha or git(base,'status','--porcelain','--ignore-submodules=none'):
        raise ValueError('Prepare requires clean exact official source')
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Exact SHA required')
    profile=check(base);os.environ['PATCHSET']=name
    output.mkdir(parents=True,exist_ok=False)
    common=output/'common'
    # Copies remove Git shared-object alternates; archives are standalone across runners.
    shutil.copytree(base,common,symlinks=True)
    run('bash',ROOT/'scripts/source/apply-patches.sh',common,'standard')
    for variant in ('standard','sos'):
        tree=output/variant;shutil.copytree(common,tree,symlinks=True)
        if variant=='sos':
            for p in sorted((ROOT/'patchsets'/name/'sos').glob('*.patch')):
                run('git','-C',tree,'apply','--check',p);run('git','-C',tree,'apply',p)
        contracts(tree,variant,name)
        run('python3',ROOT/'scripts/release/package.py','restore-bridge',tree,bridge)
        from scripts.signing.production_config import scan_bytes
        for p in tree.rglob('*'):
            if p.is_file() and '.git' not in p.relative_to(tree).parts:scan_bytes(p.read_bytes())
        if profile['source_sbom_requested']:
            run('syft','dir:'+str(tree),'-o','cyclonedx-json='+str(tree/'custom-source.sbom.json'))
        manifest={'upstream_repository':'rustdesk/rustdesk','upstream_ref':ref,'upstream_sha':sha,
                  'upstream_version':profile['upstream_version'],'patchset':name,
                  'common_patch_hash':patch_hash('common',name),
                  'sos_patch_hash':patch_hash('sos',name) if variant=='sos' else None,
                  'custom_repository':os.environ['GITHUB_REPOSITORY'],'custom_repository_sha':os.environ['GITHUB_SHA'],
                  'variant':variant,'prepare_workflow_run':os.environ['GITHUB_RUN_ID'],
                  'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'build_adapter_signature':profile['signature'],'files':inventory(tree)}
        (tree/'source-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        verify_tree(tree,variant,sha,name,os.environ['GITHUB_SHA'],os.environ['GITHUB_RUN_ID'])
        bundle=output/('prepared-'+variant);bundle.mkdir()
        archive=bundle/'source.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:tar.add(tree,arcname='source')
        shutil.copy2(tree/'source-manifest.json',bundle/'source-manifest.json')
        (bundle/'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  source.tar.gz\n')
    shutil.rmtree(common)

def unpack(bundle,destination,variant,sha,name):
    archive=bundle/'source.tar.gz';digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    if (bundle/'SHA256SUMS').read_text()!=digest+'  source.tar.gz\n':raise ValueError('Prepared archive checksum mismatch')
    destination.mkdir(parents=True,exist_ok=False)
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        for m in members:
            p=PurePosixPath(m.name)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='source':raise ValueError('Unsafe archive path')
            if m.islnk() or m.isdev() or m.isfifo():raise ValueError('Unsupported archive entry')
            if m.issym():
                resolved=(destination/m.name).parent.joinpath(m.linkname).resolve()
                if not resolved.is_relative_to(destination.resolve()):raise ValueError('Escaping source symlink')
        for m in members:
            target=(destination/m.name).resolve()
            if not target.is_relative_to(destination.resolve()):raise ValueError('Archive entry escapes through symlink')
            if m.issym() and not (destination/m.name).parent.joinpath(m.linkname).resolve().is_relative_to(destination.resolve()):
                raise ValueError('Archive symlink chain escapes')
            tar.extract(m,destination)
    tree=destination/'source'
    if (bundle/'source-manifest.json').read_bytes()!=(tree/'source-manifest.json').read_bytes():raise ValueError('Source manifest copy differs')
    verify_tree(tree,variant,sha,name,os.environ['GITHUB_SHA'],os.environ['GITHUB_RUN_ID'])
    print('Prepared source checksum/inventory/identity: PASS')
    return tree

if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare');a.add_argument('--base',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--ref',required=True);a.add_argument('--sha',required=True);a.add_argument('--patchset',required=True);a.add_argument('--bridge',type=Path,required=True)
    a=sub.add_parser('unpack');a.add_argument('--bundle',type=Path,required=True);a.add_argument('--destination',type=Path,required=True);a.add_argument('--variant',choices=['standard','sos'],required=True);a.add_argument('--sha',required=True);a.add_argument('--patchset',required=True)
    a=p.parse_args()
    if a.mode=='prepare':prepare(a.base,a.output,a.ref,a.sha,a.patchset,a.bridge)
    else:unpack(a.bundle,a.destination,a.variant,a.sha,a.patchset)
