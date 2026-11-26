"""Manual Stable/Nightly entrance to the existing credential-free v4 build core.

This is NOT release discovery, a production qualification, or a publishable draft.
Only the exact source already built from formal prepared archives is admitted here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from scripts.build import formal_validation as formal, recipe_admission

FILES={'stable':'tag.yml','nightly':'nightly.yml'}

def require(ok,message):
    if not ok:
        raise ValueError('FORMAL_DRY_RUN: '+message)

def gate(env):
    channel=env.get('FORMAL_ENTRY_CHANNEL')
    require(channel in FILES,'invalid entry channel')
    ref=env.get('GITHUB_REF','')
    repo=env.get('GITHUB_REPOSITORY')
    require(repo=='billradar/rustdesk-custom' and env.get('GITHUB_EVENT_NAME')=='workflow_dispatch'
            and ref.startswith('refs/heads/') and ref!='refs/heads/main'
            and env.get('GITHUB_WORKFLOW_REF')==repo+'/.github/workflows/'+FILES[channel]+'@'+ref,
            'explicit manual non-main entry required')
    require(env.get('RELEASE_MODE')=='dry-run' and env.get('INCLUDE_WAYLAND')=='false'
            and env.get('FORCE_RETRY')=='false','dry-run only, no Wayland or force retry')
    require(not any(env.get(k) for k in ('REQUESTED_REF','NIGHTLY_DISPLAY_LABEL','OFFICIAL_RUN_ID','ROUTER_EXPECTED_SHA')),
            'ordinary release/router source inputs must be empty')
    require(env.get('FORMAL_SOURCE_SHA')==recipe_admission.BASE,
            'only the exact previously built formal source is enabled')
    recipe_admission.source(recipe_admission.BASE)
    return recipe_admission.BASE

def digest(path):
    require(path.is_file() and not path.is_symlink(),'missing or unsafe evidence file: '+path.name)
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    digest(path)
    return json.loads(path.read_bytes())

def hex_digest(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None

def aggregate(reports,receipts):
    reports,receipts=Path(reports),Path(receipts)
    marker=formal.context(recipe_admission.BASE)
    record=recipe_admission.validate(recipe_admission.read())
    expected=record['targets']
    require({p.name for p in reports.iterdir()}=={t['report_artifact_name'] for t in expected.values()},
            'missing, extra or duplicate target report directory')
    result={};variants={}
    for target,entry in sorted(expected.items()):
        platform,arch,variant=target.split('-')
        path=reports/entry['report_artifact_name']/'package-report.json'
        report=read(path)
        require(report.get('release_eligible') is False and report.get('upstream_sha')==marker['upstream_sha']
                and report.get('variant')==variant,'report purpose/source mismatch: '+target)
        if platform=='linux':
            require(report.get('schema')=='linux-v4-ci-package-smoke-v1' and report.get('result')=='PASS'
                    and report.get('arch')==arch and report.get('package_count')==3,'Linux result mismatch: '+target)
            extensions=['.deb','.rpm','.rpm']
        else:
            require(report.get('kind')=='CI_FIXTURE_PACKAGE_SMOKE' and report.get('platform')==platform
                    and report.get('architecture')==arch and report.get('native_architecture')=='PASS'
                    and report.get('fixture_configuration_markers')=='PASS','native result mismatch: '+target)
            extensions={'android':['.apk'],'macos':['.dmg'],'windows':['.exe','.msi']}[platform]
        packages=report.get('packages',[])
        require(isinstance(packages,list) and sorted(Path(p['name']).suffix.lower() for p in packages)==extensions
                and len({p['name'] for p in packages})==len(packages)
                and all(hex_digest(p.get('sha256')) and type(p.get('size',p.get('bytes'))) is int
                        and p.get('size',p.get('bytes'))>0 for p in packages),'package inventory mismatch: '+target)
        evidence=report.get('formal_source_evidence',{})
        require(evidence.get('formal_validation')==marker and evidence.get('variant')==variant
                and evidence.get('release_eligible') is False and hex_digest(evidence.get('source_manifest_sha256')),
                'formal source evidence mismatch: '+target)
        manifest_sha=evidence['source_manifest_sha256']
        require(variants.setdefault(variant,manifest_sha)==manifest_sha,'workers consumed different prepared sources: '+target)
        if platform=='macos' and arch=='aarch64':
            folder=receipts/('v4-formal-mac-arm64-'+variant+'-receipt')
            receipt_path=folder/'macos-arm64-transform.json'
            receipt=read(receipt_path);manifest_path=folder/'source-manifest.json'
            require(digest(receipt_path)==evidence.get('macos_arm64_receipt_sha256') and
                    digest(manifest_path)==manifest_sha,'Mac receipt/source digest mismatch: '+target)
            manifest=read(manifest_path)
            from scripts.build import macos_arm64
            macos_arm64.receipt_checks(receipt,manifest,manifest_sha,formal_validation=True)
        result[target]={'report_sha256':digest(path),'source_manifest_sha256':manifest_sha,'packages':packages}
    require(set(variants)=={'standard','sos'} and variants['standard']!=variants['sos'],
            'two distinct formal variant manifests required')
    return {'schema':'formal-v4-dry-run-v1','result':'PASS','release_eligible':False,
            'formal_validation':marker,'target_count':len(result),'targets':result,
            'variant_manifest_sha256':variants,'production_signing':'NOT_TESTED',
            'runtime_ui':'NOT_TESTED','real_remote_session':'NOT_TESTED'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('gate','aggregate'))
    parser.add_argument('--reports',type=Path)
    parser.add_argument('--receipts',type=Path)
    parser.add_argument('--output',type=Path)
    a=parser.parse_args()
    if a.mode=='gate':
        print('Formal dry-run source accepted: '+gate(os.environ)+' (no release authority)')
    else:
        require(a.reports and a.receipts and a.output,'aggregate paths required')
        result=aggregate(a.reports,a.receipts)
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        print('Formal dry-run: '+str(result['target_count'])+'/13 package targets verified (no release authority)')

if __name__=='__main__':
    main()
