"""Validated reconciliation and retry transitions; all return auditable events."""
from dataclasses import replace
from datetime import timedelta
import json
import re
from uuid import UUID

from .identity import canonical, hex_value
from .model import (BuildState, Event, PolicyState, ReservationState, advance, bind, owned, utc)
from .retry import Failure, RetryPolicy
from .store import parse_time, timestamp


def provenance(record):
    return json.loads(record.source_provenance)


def updated(record, **changes):
    return canonical(dict(provenance(record), **changes)).decode()


def limits(record):
    return RetryPolicy(**provenance(record).get('retry_policy', {}))


def bind_verified(record, token, fence, run_id, custom_sha, run_attempt, now):
    hex_value(custom_sha, 40)
    if type(run_attempt) is not int or run_attempt != 1:
        raise ValueError('Native reruns require a new coordinator authorization')
    base = bind(record, token, fence, run_id, now).after
    worker = dict(workflow_run_id=run_id, custom_repository_sha=custom_sha, run_attempt=run_attempt)
    after = replace(base, source_provenance=updated(record, worker=worker))
    return Event(utc(now), 'bind_verified', record, after)


def finish(record, token, fence, started_at, completed_at, success, failure_class='', stage='', reason=''):
    owned(record, token, fence)
    utc(completed_at)
    if type(success) is not bool:
        raise ValueError('Completion requires explicit success evidence')
    after = record
    if record.state == BuildState.QUEUED and started_at is not None:
        after = advance(record, token, fence, BuildState.RUNNING, utc(started_at)).after
    elif started_at != record.started_at:
        raise ValueError('Build start evidence changed')
    if success:
        after = advance(after, token, fence, BuildState.SUCCEEDED, completed_at).after
    else:
        failure_class = Failure(failure_class).value
        after = advance(after, token, fence, BuildState.FAILED, completed_at,
                        failure_class=failure_class, failure_stage=stage, failure_reason=reason).after
    return Event(completed_at, 'finish', record, after)


def retry_schedule(record, now, next_retry_at):
    if record.state != BuildState.FAILED or 'retry_decided' in provenance(record):
        raise ValueError('Failure already classified or not terminal')
    policy = limits(record)
    if policy.eligible(record):
        lower = policy.next_retry(record, 0)
        upper = policy.next_retry(record, 1)
        if next_retry_at is None or not lower <= utc(next_retry_at) <= upper:
            raise ValueError('Retry deadline is outside bounded backoff')
    elif next_retry_at is not None:
        raise ValueError('Failure is not automatically retryable')
    after = replace(record, policy_state=PolicyState.COOLDOWN if next_retry_at else PolicyState.REVIEW_REQUIRED,
                    next_retry_at=next_retry_at, source_provenance=updated(record, retry_decided=timestamp(utc(now))))
    return Event(utc(now), 'retry_schedule', record, after)


def reserve_retry(record, token, now, lease):
    owned(record, record.reservation_id, record.fence)
    manual = provenance(record).get('manual_grant', {}).get('next_fence') == record.fence + 1
    if (record.state != BuildState.FAILED or record.policy_state != PolicyState.COOLDOWN
            or record.next_retry_at is None or utc(now) < record.next_retry_at
            or (not manual and not limits(record).eligible(record)) or utc(lease) <= now
            or str(UUID(token)) != token or token == record.reservation_id):
        raise ValueError('Retry is not authorized')
    data = provenance(record)
    for key in ('worker', 'manual_grant', 'retry_decided'):
        data.pop(key, None)
    data['reservation_created_at'] = timestamp(now)
    after = replace(record, state=BuildState.DISCOVERED, reservation_state=ReservationState.RESERVED,
                    policy_state=PolicyState.READY, reservation_id=token, fence=record.fence + 1,
                    workflow_run_id='', started_at=None, completed_at=None, lease_expires_at=lease,
                    next_retry_at=None, failure_class='', failure_stage='', failure_reason='',
                    source_provenance=canonical(data).decode())
    return Event(utc(now), 'reserve_retry', record, after)


def renew(record, token, fence, now, lease):
    owned(record, token, fence)
    if (record.state not in (BuildState.QUEUED, BuildState.RUNNING)
            or utc(lease) <= max(utc(now), record.lease_expires_at)):
        raise ValueError('Lease renewal requires a live bound run')
    return Event(utc(now), 'renew', record, replace(record, lease_expires_at=lease))


def hold(record, now, reason):
    if record.state == BuildState.SUCCEEDED or not isinstance(reason, str) or not reason or len(reason) > 200:
        raise ValueError('Invalid review decision')
    return Event(utc(now), 'hold', record, replace(record, policy_state=PolicyState.REVIEW_REQUIRED,
                 failure_reason=reason, failure_stage='reconcile', failure_class=Failure.IDENTITY.value))


def grant_retry(record, actor, reason, now):
    # Caller must independently verify the old Actions run is terminal and trusted.
    if (record.state != BuildState.FAILED or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', actor)
            or not isinstance(reason, str) or not reason.strip() or len(reason) > 500
            or any(ord(c) < 32 for c in reason)):
        raise ValueError('Manual retry requires terminal failure, actor and reason')
    grant = dict(actor=actor, reason=reason, at=timestamp(utc(now)), next_fence=record.fence + 1)
    return Event(utc(now), 'grant_retry', record, replace(record, policy_state=PolicyState.COOLDOWN,
                 next_retry_at=now, source_provenance=updated(record, manual_grant=grant, retry_decided=timestamp(now))))


def validate_additional(event):
    r, a, now = event.before, event.after, event.at
    args = (r, r.reservation_id, r.fence)
    if event.action == 'bind_verified':
        worker = provenance(a)['worker']
        expected = bind_verified(*args, a.workflow_run_id, worker['custom_repository_sha'], worker['run_attempt'], now)
    elif event.action == 'finish':
        expected = finish(*args, a.started_at, a.completed_at, a.state == BuildState.SUCCEEDED,
                          a.failure_class, a.failure_stage, a.failure_reason)
    elif event.action == 'retry_schedule':
        expected = retry_schedule(r, now, a.next_retry_at)
    elif event.action == 'reserve_retry':
        expected = reserve_retry(r, a.reservation_id, now, a.lease_expires_at)
    elif event.action == 'renew':
        expected = renew(*args, now, a.lease_expires_at)
    elif event.action == 'hold':
        expected = hold(r, now, a.failure_reason)
    elif event.action == 'grant_retry':
        grant = provenance(a)['manual_grant']
        expected = grant_retry(r, grant['actor'], grant['reason'], now)
    else:
        raise ValueError('Unsupported state event')
    if expected != event:
        raise ValueError('Event differs from validated coordinator transition')
