"""Record reviewed fixture evidence separately from release authorization.

A historical fixture pass is useful to a reviewer, never a CI qualification
artifact or permission to sign/publish. No production allowlist is mutated.
"""
import argparse
import json
from pathlib import Path
import re

from scripts.upstream import patchsets
from scripts.release.qualification import plan, gh_json

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT/'metadata/build/v4-qualification-evidence.json'
REPO = 'billradar/rustdesk-custom'
SOURCE = '51f94394ce61e1f3d26229565c326b2862cbdd1f'
SOURCE_HEAD = '54ed4f1239325f1a7fe4b3ffb56e63bd9e25883d'
TARGETS = frozenset(
    [f'{platform}-{arch}-{variant}'
     for platform, arches in (('windows', ('x86_64',)),
                              ('linux', ('x86_64','aarch64')),
                              ('macos', ('x86_64','aarch64')))
     for arch in arches for variant in ('standard','sos')] +
    [f'android-{arch}-standard' for arch in ('aarch64','armv7','x86_64')])
RUNS = {45413020202:'.github/workflows/staging-v4-desktop-mobile-packages.yml',
        45413020081:'.github/workflows/staging-v4-linux-packages.yml'}

def require(ok, message):
    if not ok:
        raise ValueError('Candidate evidence: '+message)

def positive(value):
    return type(value) is int and value > 0

def expected_name(target):
    if target.startswith('linux-'):
        return 'v4-linux-deb-rpm-'+target[len('linux-'):]+'-smoke-report'
    return 'v4-fixture-'+target+'-report'

def validate(record):
    require(record.get('schema')=='candidate-build-evidence-v1' and
            record.get('upstream_repository')=='rustdesk/rustdesk' and
            record.get('upstream_version')=='1.5.3' and record.get('upstream_sha')==SOURCE and
            record.get('evidence_custom_head_sha')==SOURCE_HEAD and record.get('patchset')=='v4' and
            positive(record.get('patchset_revision')), 'unknown source or schema')
    require(record.get('configuration')=='TEST ONLY' and
            record.get('scope')=='REQUIRED_STANDARD_SOS_MATRIX_FIXTURE_PACKAGES' and
            record.get('release_eligible') is False and
            all(record.get(k)=='NOT_TESTED' for k in ('production_signing','runtime_ui','real_remote_session')),
            'fixture record cannot claim release authority')
    hashes=record.get('patch_hashes',{})
    require(set(hashes)=={'common','sos'} and
            all(re.fullmatch(r'[0-9a-f]{64}',v) for v in hashes.values()),'invalid patch digest')
    package_runs=record.get('package_workflows',[])
    require(len(package_runs)==2 and {r['id']:r['path'] for r in package_runs}==RUNS,
            'wrong fixture workflows')
    workflows=record.get('workflows',[])
    ids=[r.get('run_id') for r in workflows]
    require(len(ids)==10 and len(set(ids))==10 and set(RUNS)<=set(ids) and
            all(positive(r.get('run_id')) and r.get('name') and r.get('result')=='PASS' for r in workflows),
            'incomplete workflow evidence')
    rows=record.get('targets',{})
    require(set(rows)==TARGETS,'missing or unexpected fixture target')
    for target,row in rows.items():
        require(set(row)=={'run_id','job_id','report_artifact_id','report_artifact_name',
                           'report_archive_digest','result'} and
                row['run_id']==(45413020081 if target.startswith('linux-') else 45413020202) and
                positive(row['job_id']) and positive(row['report_artifact_id']) and
                row['report_artifact_name']==expected_name(target) and row['result']=='PASS' and
                re.fullmatch(r'sha256:[0-9a-f]{64}',row['report_archive_digest']),
                'invalid target evidence: '+target)
    for key in ('job_id','report_artifact_id'):
        require(len({r[key] for r in rows.values()})==len(rows),'duplicate '+key)
    require(set(record.get('not_covered',[]))=={
        'windows-aarch64-standard','windows-aarch64-sos','unattended-wayland',
        'production_configuration','production_signing','runtime_ui','real_remote_session'},
        'incomplete evidence limitations')
    return record

def report(record=None):
    record=validate(record if record is not None else json.loads(RECORD.read_text()))
    actual={scope:patchsets.patch_hash(scope,'v4') for scope in ('common','sos')}
    current=patchsets.metadata('v4')
    required={row['id'] for row in plan('ci')['selected'] if row['required']}
    stable={row['id'] for row in plan('stable')['selected']}
    missing=sorted(required-set(record['targets']))
    fresh=actual==record['patch_hashes'] and current['revision']==record['patchset_revision']
    return {'result':'STALE_PATCH_CONTENT' if not fresh else 'INCOMPLETE_REQUIRED_MATRIX' if missing else 'FIXTURE_VERIFIED',
            'upstream_sha':record['upstream_sha'],'evidence_custom_head_sha':record['evidence_custom_head_sha'],
            'verified_fixture_targets':len(record['targets']),'missing_required_targets':missing,
            'unverified_stable_targets':sorted(stable-set(record['targets'])),
            'not_covered':record['not_covered'],'release_eligible':False,
            'next_gate':'PRODUCTION_RECIPE_AND_CONFIG_SIGNING_RUNTIME_REVIEW'}

def verify_live(record):
    """Optional read-only recheck while the report archives are retained."""
    record=validate(record)
    for row in record['workflows']:
        run=gh_json(f'repos/{REPO}/actions/runs/{row["run_id"]}')
        require(run.get('head_sha')==SOURCE_HEAD and run.get('status')=='completed' and
                run.get('conclusion')=='success' and run.get('name')==row['name'],
                'workflow run identity drift')
    for run_id,path in RUNS.items():
        run=gh_json(f'repos/{REPO}/actions/runs/{run_id}')
        require(run.get('path','').split('@',1)[0]==path,'unexpected workflow path')
        jobs=gh_json(f'repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100')['jobs']
        arts=gh_json(f'repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100')['artifacts']
        for target,row in record['targets'].items():
            if row['run_id']!=run_id:
                continue
            job=[j for j in jobs if j['id']==row['job_id']]
            art=[a for a in arts if a['id']==row['report_artifact_id']]
            require(len(job)==1 and job[0]['conclusion']=='success' and
                    job[0]['name']==('Real DEB/RPM Linux '+target[len('linux-'):].replace('-',' ')+' (no publication)'
                                     if target.startswith('linux-') else
                                     'Fixture '+target.replace('-',' ')+' (no publication)'),
                    'missing or mismatched successful target job: '+target)
            require(len(art)==1 and not art[0]['expired'] and
                    art[0]['name']==row['report_artifact_name'] and art[0]['digest']==row['report_archive_digest'],
                    'missing, expired or mismatched report archive: '+target)
    return True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    record=json.loads(RECORD.read_text())
    if args.live:
        verify_live(record)
    print(json.dumps(report(record),indent=2))

if __name__=='__main__':
    main()
