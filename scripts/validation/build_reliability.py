#!/usr/bin/env python3
"""Record every target's scheduling evidence and selectively recover infrastructure failures."""
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

WORKFLOWS = {'.github/workflows/tag.yml', '.github/workflows/nightly.yml'}
MAX_ATTEMPTS = 3


def gh(*args):
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout


def api(path):
    return json.loads(gh('api', path))


def pages(path, key=None):
    rows = []
    for page in range(1, 101):
        batch = api(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
        batch = batch[key] if key else batch
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise ValueError('Reliability evidence pagination limit reached')


def latest_jobs(rows):
    """Keep each logical job's newest execution, including prior successful targets."""
    found = {}
    for row in rows:
        key = row['name']
        order = lambda job: (job.get('run_attempt', 0), job.get('created_at') or '', job['id'])
        if key not in found or order(row) > order(found[key]):
            found[key] = row
    return list(found.values())


def seconds(start, end):
    if not start or not end:
        return None
    return max(0, int((datetime.fromisoformat(end.replace('Z', '+00:00')) -
                       datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds()))


def target_job(job):
    # Only leaf compilation jobs; never source preparation, aggregate, signing or publication.
    return bool(re.search(r' / (?:android|linux|macos)-(?:x86_64|aarch64|armv7)-(?:standard|sos)$', job['name'])
                or re.search(r' / unattended-wayland-(?:standard|sos)-(?:x86_64|aarch64)$', job['name'])
                or re.search(r'^(?:windows-build|04A · Build Stable Windows targets) / build/windows-(?:standard|sos|aarch64-standard|aarch64-sos)$', job['name']))


def classify(job, annotations, log):
    if job.get('conclusion') == 'success':
        return 'PASS'
    if job.get('conclusion') == 'skipped':
        return 'SKIPPED'
    if job.get('conclusion') not in ('failure', 'cancelled'):
        return 'UNKNOWN'
    messages = '\n'.join(a.get('message', '') for a in annotations)
    if not job.get('steps') and ('Due to capacity constraints' in messages or
            'The job was not acquired by Runner of type hosted' in messages):
        return 'RUNNER_CAPACITY'
    if 'The runner has received a shutdown signal.' in log:
        return 'RUNNER_SHUTDOWN'
    # Specific SDK installer evidence, not a generic compiler/Gradle exception.
    if ('INFRASTRUCTURE: SDK_INSTALL_RETRY_EXHAUSTED' in log or
            ('Archive is not a ZIP archive' in log and
             'Install Android SDK Platform' in log and 'Failed to install the following SDK components' in log)):
        return 'SDK_DOWNLOAD'
    return 'BUILD_OR_UNKNOWN'


def report_job(job, reason):
    executed = bool(job.get('steps'))
    return dict(id=job['id'], name=job['name'], conclusion=job.get('conclusion'),
                runner_labels=job.get('labels', []), runner_name=job.get('runner_name', ''),
                created_at=job.get('created_at'), started_at=job.get('started_at'),
                completed_at=job.get('completed_at'), executed_steps=executed,
                queue_seconds=seconds(job.get('created_at'), job.get('started_at')) if executed else None,
                unassigned_seconds=seconds(job.get('created_at'), job.get('completed_at')) if not executed and reason == 'RUNNER_CAPACITY' else None,
                execution_seconds=seconds(job.get('started_at'), job.get('completed_at')) if executed else None,
                reason=reason, retry_eligible=target_job(job) and reason in ('RUNNER_CAPACITY', 'RUNNER_SHUTDOWN', 'SDK_DOWNLOAD')
                and not any(s.get('conclusion') == 'success' and s.get('name', '').startswith('Upload ') for s in job.get('steps', [])))


def verify_run(run, repo):
    if (run.get('repository', {}).get('full_name') != repo
            or run.get('head_repository', {}).get('full_name') != repo
            or run.get('event') != 'workflow_dispatch' or run.get('head_branch') != 'main'
            or run.get('path', '').split('@')[0] not in WORKFLOWS
            or run.get('status') != 'completed'
            or not re.fullmatch(r'[0-9a-f]{40}', run.get('head_sha', ''))):
        raise ValueError('Untrusted build recovery context')
    # Publication mode must always be explicitly handled by a human.
    title = run.get('display_title', '')
    return bool(re.search(r' / (?:dry-run|draft) / wayland=(?:true|false) / android-signing=(?:true|false)(?: / identity=(?:auto|manual|[0-9a-f]{64}))?$', title))


def process(event, repo, output):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid repository')
    incoming = event['workflow_run']
    run_id = int(incoming['id'])
    run = api(f'repos/{repo}/actions/runs/{run_id}')
    retry_mode = verify_run(dict(run, status='completed'), repo)
    if (run.get('status') != 'completed' or run.get('run_attempt') != incoming.get('run_attempt')
            or run['head_sha'] != incoming['head_sha']):
        report = dict(schema='build-reliability-v1', run_id=run_id,
                      event_attempt=incoming.get('run_attempt'), current_attempt=run.get('run_attempt'),
                      recovery='SKIPPED_STALE_EVENT')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        return report
    jobs = latest_jobs(pages(f'repos/{repo}/actions/runs/{run_id}/jobs?filter=all', 'jobs'))
    report = dict(schema='build-reliability-v1', run_id=run_id, attempt=run['run_attempt'],
                  custom_sha=run['head_sha'], workflow=run['path'], created_at=run['created_at'],
                  observed_at=datetime.now(timezone.utc).isoformat(), jobs=[], recovery='NOT_NEEDED')
    for job in jobs:
        annotations, log = [], ''
        if job.get('conclusion') in ('failure', 'cancelled'):
            check = re.fullmatch(r'https://api.github.com/repos/' + re.escape(repo) + r'/check-runs/([1-9][0-9]*)', job.get('check_run_url', ''))
            if check:
                annotations = pages(f'repos/{repo}/check-runs/{check.group(1)}/annotations')
            if target_job(job) and job.get('steps'):
                try:
                    log = gh('api', f'repos/{repo}/actions/jobs/{job["id"]}/logs')
                except subprocess.CalledProcessError:
                    pass  # Unknown is not retryable; no raw log output/persistence.
        reason = classify(job, annotations, log)
        report['jobs'].append(report_job(job, reason))
    candidates = [j for j in report['jobs'] if j['retry_eligible']]
    output.parent.mkdir(parents=True, exist_ok=True)
    # Save evidence before any mutation, and update it even when the API rejects a retry.
    try:
        if candidates:
            report['recovery'] = 'MANUAL_REVIEW'
            if (retry_mode and run['conclusion'] == 'failure' and run['run_attempt'] < MAX_ATTEMPTS
                    and os.environ.get('BUILD_INFRA_AUTO_RETRY_ENABLED', 'true') == 'true'):
                # Only trusted main history may regain the original workflow's privileges.
                comparison = api(f'repos/{repo}/compare/{run["head_sha"]}...main')
                if comparison['status'] not in ('ahead', 'identical'):
                    raise ValueError('Recovery source is not in main history')
                fresh = api(f'repos/{repo}/actions/runs/{run_id}')
                if fresh['status'] != 'completed' or fresh['run_attempt'] != run['run_attempt']:
                    raise ValueError('Run changed while selecting recovery')
                chosen = candidates[0]
                report.update(recovery='REQUESTING', retry_job_id=chosen['id'])
                output.write_text(json.dumps(report, indent=2) + '\n')
                gh('api', '--method', 'POST', f'repos/{repo}/actions/jobs/{chosen["id"]}/rerun')
                report['recovery'] = 'REQUESTED'
        return report
    finally:
        output.write_text(json.dumps(report, indent=2) + '\n')
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                stream.write(f'## Build reliability: run {run_id}, attempt {run["run_attempt"]}\n\n'
                             f'Recovery: {report["recovery"]}. One infrastructure job per completion; '
                             f'maximum {MAX_ATTEMPTS} run attempts.\n\n'
                             '| Job ID | Result | Evidence | Queue seconds |\n|---|---|---|---|\n')
                for job in report['jobs']:
                    stream.write(f'| {job["id"]} | {job["conclusion"]} | {job["reason"]} | {job["queue_seconds"]} |\n')


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    process(event, os.environ['GITHUB_REPOSITORY'], Path('.work/build-reliability/report.json'))


if __name__ == '__main__':
    main()
