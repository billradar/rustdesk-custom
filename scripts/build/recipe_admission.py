"""Source-scoped approval of production recipes, not release authorization.

The explicit review mode exercises the same official adapters without altering
Stable/Nightly Patch Profile admission or accepting CI receipts as production.
The dry-run orchestrator must explicitly opt in at the next qualification gate.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from scripts.upstream import patchsets
from scripts.release import candidate_evidence

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT/'metadata/build/v4-production-recipe-admission.json'
BASE = '51f94394ce61e1f3d26229565c326b2862cbdd1f'
SUCCESSOR = 'a0c0963c483fc8f1aeed4547787d1673adcb583c'
HEAD = 'f397a7855c9f9189f023d6a7be3c3eaf028ce20d'
CHANNELS = ('stable','nightly')

def require(ok,message):
    if not ok:
        raise ValueError('PRODUCTION_RECIPE_ADMISSION: '+message)

def read():
    return json.loads(POLICY.read_text())

def validate(record):
    require(record.get('schema')=='production-recipe-admission-v1' and
            record.get('decision')=='APPROVED_FOR_FORMAL_BUILD_VALIDATION' and
            record.get('upstream_repository')=='rustdesk/rustdesk' and
            record.get('upstream_version')=='1.5.3' and record.get('patchset')=='v4' and
            record.get('fixture_source_sha')==BASE and record.get('evidence_custom_head_sha')==HEAD,
            'invalid admission identity')
    require(record.get('release_eligible') is False and
            all(record.get(k)=='NOT_TESTED' for k in ('production_signing','runtime_ui','real_remote_session')),
            'recipe approval is not a release approval')
    require(set(record.get('excluded',[]))=={'windows-aarch64-standard','windows-aarch64-sos',
            'unattended-wayland','android-sos','ios','web'},'exclusion policy drift')
    expected=patchsets.verify('v4')
    require(record.get('revision')==expected['revision'] and
            record.get('patch_hashes')==expected['hashes'],'patch content changed after review')
    targets=record.get('targets',{})
    require(set(targets)==candidate_evidence.TARGETS,'incomplete reviewed matrix')
    for target,row in targets.items():
        require(row.get('result')=='PASS' and
                row.get('run_id')==(45538522799 if target.startswith('linux-') else 45538522871) and
                candidate_evidence.positive(row.get('job_id')) and
                candidate_evidence.positive(row.get('report_artifact_id')) and
                row.get('report_artifact_name')==candidate_evidence.expected_name(target) and
                re.fullmatch(r'sha256:[0-9a-f]{64}',row.get('report_archive_digest','')),
                'invalid fixture evidence: '+target)
    for key in ('job_id','report_artifact_id'):
        require(len({row[key] for row in targets.values()})==13,'duplicate '+key)
    runs=record.get('workflow_runs',[])
    require(len(runs)==11 and len({r['run_id'] for r in runs})==11 and
            all(r['result']=='PASS' for r in runs) and
            {45538522535,45538522799,45538522871}<={r['run_id'] for r in runs},
            'incomplete workflow evidence')
    sources=record.get('sources',{})
    require(set(sources)=={BASE,SUCCESSOR},'unapproved source scope')
    from scripts.platform.platform_adapter import CI_PLATFORM_RUNNERS
    for sha,row in sources.items():
        require(row.get('fixture_source_sha')==BASE and
                row.get('qualification')==('FIXTURE_PACKAGE_PASS' if sha==BASE else 'UNCHANGED_BUILD_INPUTS_AND_MAIN_CI_PASS') and
                re.fullmatch(r'[0-9a-f]{64}',row.get('build_signature','')) and
                set(row.get('platforms',{}))==set(CI_PLATFORM_RUNNERS),'invalid source approval')
        for platform,p in row['platforms'].items():
            require(p.get('runners')==CI_PLATFORM_RUNNERS[platform] and
                    re.fullmatch(r'[0-9a-f]{64}',p.get('signature','')),
                    'invalid reviewed platform scope')
    require(sources[BASE]['build_signature']==sources[SUCCESSOR]['build_signature'] and
            sources[BASE]['platforms']==sources[SUCCESSOR]['platforms'],'successor recipe drift')
    comparison=json.loads((ROOT/'metadata/build/a0c0963c-ci-source-review.json').read_text())
    require(comparison.get('base_source_sha')==BASE and comparison.get('candidate_source_sha')==SUCCESSOR and
            comparison.get('comparison')==record.get('successor_comparison') and
            comparison.get('candidate_actual_package_status')=='NOT_TESTED' and
            comparison.get('stable_allowed') is False and
            {r['path'] for r in comparison['changed_entries']}==
            {'.github/pull_request_template.md','.github/workflows/pr-evidence-check.yml'} and
            all(r['before'] is None for r in comparison['changed_entries']),
            'successor source comparison is missing or changed')
    return record

def source(sha):
    record=validate(read())
    require(sha in record['sources'],'unapproved exact source')
    selection=patchsets.profile_for_version('1.5.3','ci',source_sha=sha)
    require(selection['selected']=='v4' and selection['source_match'] and
            selection['compatibility_test_only'] and not selection['stable_allowed'],
            'candidate/release boundary changed')
    return record['sources'][sha]

def annotations(sha):
    return dict(production_recipe_approved=True,recipe_admission_source_sha=sha,
                release_eligible=False,recipe_review_status='APPROVED_FOR_FORMAL_BUILD_VALIDATION')

def check_build(row,profile):
    sha=row['source_sha']
    policy=source(sha)
    require(profile['upstream_version']=='1.5.3' and
            profile['signature']==policy['build_signature']==row['signature'],
            'common build signature mismatch')
    return dict(profile,**annotations(sha))

def check_platform(profile,platform,arch):
    sha=profile['candidate_source_sha']
    approved=source(sha)['platforms'].get(platform,{})
    require(arch in approved.get('runners',{}) and
            profile['signature']==approved.get('signature') and
            profile['runner']==approved['runners'][arch],
            'platform signature or architecture not approved')
    return dict(profile,**annotations(sha))

def inspect_source(tree, *, if_admitted=False):
    from scripts.build import build_adapter
    from scripts.platform import platform_adapter
    sha=subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD'],text=True).strip()
    if if_admitted and sha not in (BASE,SUCCESSOR):
        return {'result':'NOT_IN_FORMAL_RECIPE_SCOPE','upstream_sha':sha,'release_eligible':False}
    row=source(sha)
    common=build_adapter.check(tree,channel='stable',recipe_review=True)
    platforms={}
    for name,p in row['platforms'].items():
        for arch in p['runners']:
            profile,_=platform_adapter.check(tree,name,arch,channel='stable',recipe_review=True)
            require(profile.get('production_recipe_approved') is True and profile.get('release_eligible') is False,
                    'formal review boundary lost')
            platforms[name+'-'+arch]=profile
    require(common.get('production_recipe_approved') is True and common.get('release_eligible') is False,
            'common recipe review boundary lost')
    return {'result':'PASS','upstream_sha':sha,'qualification':row['qualification'],
            'common_build':common,'platforms':platforms,'release_eligible':False,
            'next_gate':'FORMAL_DRY_RUN_WITH_PREPARED_SOURCE_AND_PRODUCTION_RECEIPTS'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('tree',type=Path)
    parser.add_argument('--if-admitted',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=inspect_source(args.tree,if_admitted=args.if_admitted)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('Production recipe review: '+report['result']+' (release authorization unchanged)')

if __name__=='__main__':
    main()
