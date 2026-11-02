"""Immutable state vocabulary. Persistence and authenticated writers are separate."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from .identity import hex_value


class BuildState(str, Enum):
    DISCOVERED = 'DISCOVERED'
    QUEUED = 'QUEUED'
    RUNNING = 'RUNNING'
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'


class ReservationState(str, Enum):
    NONE = 'NONE'
    RESERVED = 'RESERVED'
    DISPATCH_UNKNOWN = 'DISPATCH_UNKNOWN'
    BOUND = 'BOUND'


class PolicyState(str, Enum):
    READY = 'READY'
    COOLDOWN = 'COOLDOWN'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'


def utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("An aware UTC timestamp is required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Record:
    channel: str
    build_identity: str
    upstream_sha: str
    created_at: datetime
    # Canonical immutable JSON, not a mutable dictionary.
    source_provenance: str
    schema_version: int = 1
    state: BuildState = BuildState.DISCOVERED
    reservation_state: ReservationState = ReservationState.NONE
    policy_state: PolicyState = PolicyState.READY
    reservation_id: str = ''
    fence: int = 0
    workflow_run_id: str = ''
    attempt: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    next_retry_at: datetime | None = None
    failure_class: str = ''
    failure_stage: str = ''
    failure_reason: str = ''

    def __post_init__(self):
        import json
        from .identity import canonical
        if (type(self.schema_version) is not int or self.schema_version != 1
                or self.channel not in ('stable', 'nightly')
                or not isinstance(self.state, BuildState)
                or not isinstance(self.reservation_state, ReservationState)
                or not isinstance(self.policy_state, PolicyState)):
            raise ValueError("Unsupported record schema/state")
        hex_value(self.build_identity, 64)
        hex_value(self.upstream_sha, 40)
        if (type(self.attempt) is not int or self.attempt < 0
                or type(self.fence) is not int or self.fence < 0):
            raise ValueError("Invalid counter")
        provenance = json.loads(self.source_provenance)
        if type(provenance) is not dict or canonical(provenance).decode() != self.source_provenance:
            raise ValueError("Provenance must be a canonical JSON object")
        for value in (self.created_at, self.started_at, self.completed_at,
                      self.lease_expires_at, self.next_retry_at):
            if value is not None:
                utc(value)
        if self.started_at and self.started_at < self.created_at:
            raise ValueError("Start precedes discovery")
        if self.completed_at and self.completed_at < (self.started_at or self.created_at):
            raise ValueError("Completion precedes start/discovery")
        if self.reservation_state != ReservationState.NONE:
            if (str(UUID(self.reservation_id)) != self.reservation_id
                    or self.fence < 1 or self.lease_expires_at is None):
                raise ValueError("Reservation requires a UUID, fence and lease")
        elif self.reservation_id or self.fence or self.lease_expires_at:
            raise ValueError("Unreserved record has reservation fields")
        if self.workflow_run_id:
            import re
            if not re.fullmatch('[1-9][0-9]*', self.workflow_run_id):
                raise ValueError("Invalid workflow run")
        if self.reservation_state == ReservationState.BOUND and not self.workflow_run_id:
            raise ValueError("Bound reservation requires a run")
        if self.state != BuildState.DISCOVERED and self.reservation_state != ReservationState.BOUND:
            raise ValueError("Build state requires a bound reservation")
        if self.state in (BuildState.RUNNING, BuildState.SUCCEEDED) and not self.started_at:
            raise ValueError("Started build evidence missing")
        if self.started_at and self.attempt < 1:
            raise ValueError("Started build requires a real attempt")
        if self.state in (BuildState.SUCCEEDED, BuildState.FAILED) and not self.completed_at:
            raise ValueError("Terminal build requires completion evidence")


def owned(record, reservation_id, fence):
    if (record.reservation_id != reservation_id or record.fence != fence
            or record.reservation_state == ReservationState.NONE):
        raise ValueError("Stale reservation writer")


@dataclass(frozen=True)
class Event:
    at: datetime
    action: str
    before: Record
    after: Record


def reserve(record, reservation_id, now, lease):
    utc(now)
    utc(lease)
    if (record.state != BuildState.DISCOVERED
            or record.reservation_state != ReservationState.NONE
            or record.policy_state != PolicyState.READY
            or now < record.created_at or lease <= now):
        raise ValueError("Record is not reservable")
    after = replace(record, reservation_id=reservation_id, fence=record.fence + 1,
                    reservation_state=ReservationState.RESERVED, lease_expires_at=lease)
    return Event(now, 'reserve', record, after)


def dispatch_unknown(record, reservation_id, fence, now):
    owned(record, reservation_id, fence)
    if record.reservation_state != ReservationState.RESERVED:
        raise ValueError("Dispatch intent is not pending")
    return Event(utc(now), 'dispatch_unknown', record,
                 replace(record, reservation_state=ReservationState.DISPATCH_UNKNOWN,
                         policy_state=PolicyState.REVIEW_REQUIRED))


def bind(record, reservation_id, fence, run_id, now):
    """Requires verified run/token evidence from a future reconciler."""
    owned(record, reservation_id, fence)
    if record.reservation_state not in (ReservationState.RESERVED, ReservationState.DISPATCH_UNKNOWN):
        raise ValueError("Reservation is already bound")
    after = replace(record, workflow_run_id=run_id, state=BuildState.QUEUED,
                    reservation_state=ReservationState.BOUND, policy_state=PolicyState.READY)
    return Event(utc(now), 'bind', record, after)


def advance(record, reservation_id, fence, state, now, *,
            failure_class='', failure_stage='', failure_reason=''):
    owned(record, reservation_id, fence)
    utc(now)
    allowed = {BuildState.QUEUED: {BuildState.RUNNING, BuildState.FAILED},
               BuildState.RUNNING: {BuildState.SUCCEEDED, BuildState.FAILED}}
    if state not in allowed.get(record.state, set()):
        raise ValueError("Invalid build transition")
    if now < (record.started_at or record.created_at):
        raise ValueError("Out-of-order build evidence")
    changes = dict(state=state)
    if state == BuildState.RUNNING:
        changes.update(started_at=now, attempt=record.attempt + 1)
    else:
        changes['completed_at'] = now
        if state == BuildState.FAILED:
            if not failure_class or not failure_stage or not failure_reason:
                raise ValueError("Failure evidence is required")
            changes.update(failure_class=failure_class, failure_stage=failure_stage,
                           failure_reason=failure_reason, policy_state=PolicyState.REVIEW_REQUIRED)
    return Event(now, 'advance', record, replace(record, **changes))
