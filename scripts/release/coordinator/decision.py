"""Pure, conservative admission decisions; no dispatch or production credentials."""
from enum import Enum

from .model import BuildState, PolicyState, ReservationState, utc


class Decision(str, Enum):
    RESERVE = 'RESERVE'
    ACTIVE = 'ACTIVE'
    SUCCESS = 'SUCCESS'
    COOLDOWN = 'COOLDOWN'
    RECONCILE = 'RECONCILE'
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'


def decide(record, now, *, history_verified=False):
    utc(now)
    # Missing/expired artifacts are not proof of absence of a historical build.
    if not history_verified:
        return Decision.REVIEW_REQUIRED
    if record is None:
        return Decision.RESERVE
    if record.state == BuildState.SUCCEEDED:
        return Decision.SUCCESS
    if record.reservation_state == ReservationState.DISPATCH_UNKNOWN:
        return Decision.RECONCILE
    if (record.reservation_state != ReservationState.NONE
            and record.lease_expires_at <= now):
        # Expiry never authorizes replacement or dispatch without Actions evidence.
        return Decision.RECONCILE
    if record.state in (BuildState.QUEUED, BuildState.RUNNING):
        return Decision.ACTIVE
    if record.policy_state == PolicyState.REVIEW_REQUIRED or record.state == BuildState.FAILED:
        return Decision.REVIEW_REQUIRED
    if record.policy_state == PolicyState.COOLDOWN:
        # Retry authorization is a later policy transition, not an expired timer.
        return Decision.COOLDOWN if record.next_retry_at and now < record.next_retry_at else Decision.RECONCILE
    if record.reservation_state == ReservationState.RESERVED:
        return Decision.ACTIVE
    return Decision.RESERVE
