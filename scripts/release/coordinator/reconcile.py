"""Recover journal state from trusted Actions evidence, never from elapsed time."""
from datetime import timedelta
import json
import re

from scripts.validation.build_reliability import classify, gh, latest_jobs, target_job
from .model import BuildState, PolicyState, ReservationState, advance
from .retry import Failure
from .store import APIError, parse_time
from .transitions import (finish, hold, limits, observe_start, provenance, renew, retry_schedule)

COMPILE_STEPS = {'Official-compatible compile, package and independent gates',
                 'Build and verify selected variant'}
WORKFLOWS = {'stable': '.github/workflows/tag.yml', 'nightly': '.github/workflows/nightly.yml'}
SIGNING_JOBS = {'android-sign', '05 · Sign Stable Android production artifacts (YubiKey PIV 9C)',
                'Sign Nightly Android production artifacts (YubiKey PIV 9C)'}
MISSING_REASON = 'Actions evidence unavailable (404); stopped-run operator review required'


def same_run(first, second):
    return all(first.get(k) == second.get(k) for k in ('id', 'status', 'conclusion', 'run_attempt', 'head_sha'))


def log_decision(record, decision):
    print(json.dumps(dict(schema_version=1, channel=record.channel, build_identity=record.build_identity,
                         reservation_id=record.reservation_id, fence=record.fence, attempt=record.attempt,
                         run_id=record.workflow_run_id, state=record.state.value,
                         policy=record.policy_state.value, decision=decision), sort_keys=True))


class ActionsEvidence:
    def __init__(self, api, repository, *, logs=None):
        self.api, self.repository = api, repository
        # CLI follows the Actions log download redirect; raw log content is
        # inspected in memory only, never emitted or added to the journal.
        self.logs = logs or (lambda job: gh('api', f'repos/{repository}/actions/jobs/{job}/logs'))

    def run(self, record):
        run = self.api.request('GET', f'repos/{self.repository}/actions/runs/{record.workflow_run_id}')
        worker = provenance(record).get('worker', {})
        if (str(run.get('id')) != record.workflow_run_id
                or run.get('repository', {}).get('full_name') != self.repository
                or run.get('head_repository', {}).get('full_name') != self.repository
                or run.get('head_branch') != 'main' or run.get('event') != 'workflow_dispatch'
                or run.get('path', '').split('@')[0] != WORKFLOWS[record.channel]
                or run.get('head_sha') != worker.get('custom_repository_sha')
                or type(run.get('run_attempt')) is not int
                or run.get('run_attempt') != worker.get('run_attempt')
                or worker.get('workflow_run_id') != record.workflow_run_id):
            raise ValueError('Run provenance/attempt mismatch')
        return run

    def jobs(self, record):
        rows = []
        for page in range(1, 101):
            result = self.api.request('GET', f'repos/{self.repository}/actions/runs/{record.workflow_run_id}/jobs?filter=all&per_page=100&page={page}')
            batch = result['jobs']
            expected_attempt = provenance(record)['worker']['run_attempt']
            if any(type(j.get('run_attempt')) is not int or j['run_attempt'] != expected_attempt for j in batch):
                raise ValueError('Job evidence contains an unauthorized run attempt')
            rows.extend(batch)
            if len(batch) < 100:
                return latest_jobs(rows)
        raise ValueError('Job pagination incomplete')

    def failure(self, run, jobs):
        if run.get('conclusion') == 'cancelled':
            return Failure.CANCELLED, 'workflow', 'User or workflow cancellation'
        failures = [j for j in jobs if j.get('conclusion') not in ('success', 'skipped', None)]
        if not failures:
            return Failure.UNKNOWN, 'workflow', 'No trustworthy failure-stage evidence'
        for job in failures:
            if job.get('name') in SIGNING_JOBS:
                return Failure.SIGNING, job['name'], 'Production signing or signing gate failed'
        categories = []
        for job in failures:
            name = job.get('name', '')
            if not target_job(job):
                return Failure.UNKNOWN, name, 'Non-leaf build or safety gate failed'
            try:
                reason = classify(job, [], self.logs(job['id']))
            except Exception:
                reason = 'UNKNOWN'
            category = {'RUNNER_SHUTDOWN': Failure.SHUTDOWN, 'SDK_DOWNLOAD': Failure.SDK}.get(reason)
            if category is None:
                return Failure.UNKNOWN, name, 'Build failure lacks explicit transient evidence'
            categories.append((category, name, reason))
        return categories[0]


def build_start(jobs):
    starts = [parse_time(s['started_at']) for j in jobs if target_job(j)
              for s in (j.get('steps') or []) if s.get('name') in COMPILE_STEPS
              and (s.get('status') == 'in_progress' or (s.get('status') == 'completed'
                   and s.get('conclusion') in ('success', 'failure', 'cancelled', 'timed_out')))
              and s.get('conclusion') not in ('skipped', 'neutral') and s.get('started_at')]
    return min(starts) if starts else None


class Reconciler:
    def __init__(self, journal, evidence):
        self.journal, self.evidence = journal, evidence

    def refresh(self, snapshot, now, *, sample=None):
        r = snapshot.record
        if r.state == BuildState.SUCCEEDED:
            return snapshot
        if r.reservation_state != ReservationState.BOUND:
            log_decision(r, 'DISPATCH_RECONCILIATION_REQUIRED')
            # Do not assume a timed-out dispatch was rejected; admission may
            # still bind a late arriving verified run to this reservation.
            return snapshot
        try:
            run = self.evidence.run(r)
            jobs = self.evidence.jobs(r)
            fresh = self.evidence.run(r)
        except ValueError:
            return self.journal.append(hold(r, now, 'Run provenance or attempt changed; operator review required'), snapshot)
        except APIError as error:
            if error.status != 404:
                raise
            reason = MISSING_REASON
            if r.policy_state == PolicyState.REVIEW_REQUIRED and r.failure_reason == reason:
                return snapshot
            return self.journal.append(hold(r, now, reason), snapshot)
        if not same_run(run, fresh):
            log_decision(r, 'DEFER_CHANGED_RUN')
            return snapshot
        started = build_start(jobs)
        if run['status'] != 'completed':
            if r.state in (BuildState.SUCCEEDED, BuildState.FAILED):
                return self.journal.append(hold(r, now, 'Terminal journal conflicts with active Actions run'), snapshot)
            if r.state == BuildState.QUEUED and started is not None:
                snapshot = self.journal.append(observe_start(r, r.reservation_id, r.fence, started, now), snapshot)
                r = snapshot.record
            if r.lease_expires_at <= now:
                snapshot = self.journal.append(renew(r, r.reservation_id, r.fence, now, now + timedelta(hours=6)), snapshot)
            log_decision(snapshot.record, 'ACTIVE_NO_STEAL')
            return snapshot
        if r.state != BuildState.FAILED:
            completions = [parse_time(j['completed_at']) for j in jobs if j.get('completed_at')]
            if not completions:
                return self.journal.append(hold(r, now, 'Missing actual completion evidence'), snapshot)
            # Actions workflow runs have no reliable completed_at field. The
            # final observed job completion is the completion evidence, not
            # created_at/updated_at (which also move on reruns).
            completed = max(completions)
            successful = run.get('conclusion') == 'success'
            if successful and (started is None or not any(
                    j.get('conclusion') == 'success' and (
                        j.get('name') in ('aggregate', '06 · Aggregate and verify Stable production artifacts'))
                    for j in jobs)):
                return self.journal.append(hold(r, now, 'Success lacks actual build/aggregate evidence'), snapshot)
            category, stage, reason = self.evidence.failure(run, jobs) if not successful else ('', '', '')
            event = finish(r, r.reservation_id, r.fence, started, completed, successful,
                           category.value if isinstance(category, Failure) else category, stage, reason, observed_at=now)
            try:
                final_run = self.evidence.run(r)
            except ValueError:
                return self.journal.append(hold(r, now, 'Run attempt changed while classifying completion'), snapshot)
            except APIError as error:
                if error.status != 404:
                    raise
                return self.journal.append(hold(r, now, MISSING_REASON), snapshot)
            if not same_run(run, final_run):
                log_decision(r, 'DEFER_CHANGED_RUN')
                return snapshot
            snapshot = self.journal.append(event, snapshot)
            r = snapshot.record
        if r.state == BuildState.FAILED and 'retry_decided' not in provenance(r):
            snapshot = self.journal.append(retry_schedule(r, now, limits(r).next_retry(r, sample)), snapshot)
        log_decision(snapshot.record, 'RECONCILED')
        return snapshot
