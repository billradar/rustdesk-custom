"""Classified, bounded retry policy. Workflow 'failure' alone is not evidence."""
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
import math
import random
import json

from .model import BuildState, utc


class Failure(str, Enum):
    NETWORK = 'TRANSIENT_NETWORK'
    API_5XX = 'GITHUB_API_5XX'
    RUNNER = 'RUNNER_UNAVAILABLE'
    SHUTDOWN = 'RUNNER_SHUTDOWN'
    SDK = 'SDK_DOWNLOAD'
    PATCH = 'PATCH_FAILURE'
    COMPILE = 'COMPILE_FAILURE'
    CONTRACT = 'CONTRACT_FAILURE'
    SIGNING = 'PRODUCTION_SIGNING_FAILURE'
    INTEGRITY = 'SHA_ARTIFACT_FAILURE'
    IDENTITY = 'IDENTITY_UNKNOWN'
    CANCELLED = 'USER_CANCELLED'
    SECURITY = 'SECURITY_GATE_REJECTED'
    UNKNOWN = 'UNKNOWN'


AUTOMATIC = {Failure.NETWORK, Failure.API_5XX, Failure.RUNNER, Failure.SHUTDOWN, Failure.SDK}


def uncertain_attempts(record):
    value=json.loads(record.source_provenance).get('missing_run_uncertain_attempts',0)
    if type(value) is not int or value<0:
        raise ValueError('Invalid missing-run uncertainty budget')
    return value


def budget_attempts(record):
    return record.attempt+uncertain_attempts(record)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    max_reservations: int = 6
    base_seconds: int = 21600
    cap_seconds: int = 86400

    def __post_init__(self):
        for value in (self.max_attempts, self.max_reservations, self.base_seconds, self.cap_seconds):
            if type(value) is not int or value < 1:
                raise ValueError('Invalid retry policy')
        if self.max_attempts > 10 or self.max_reservations > 30 or self.base_seconds > self.cap_seconds:
            raise ValueError('Retry policy exceeds reviewed bounds')

    def eligible(self, record):
        return (record.state == BuildState.FAILED and record.failure_class in AUTOMATIC
                and budget_attempts(record) < self.max_attempts and record.fence < self.max_reservations)

    def delay(self, record):
        # Failed reservations have their own finite budget, not fake build attempts.
        exponent = max(record.attempt - 1, record.fence - 1, 0)
        return min(self.cap_seconds, self.base_seconds * 2 ** min(exponent, 30))

    def next_retry(self, record, sample=None):
        if not self.eligible(record):
            return None
        sample = random.random() if sample is None else sample
        if type(sample) not in (int, float) or not math.isfinite(sample) or not 0 <= sample <= 1:
            raise ValueError('Invalid jitter sample')
        # Persistent event stores the selected UTC deadline, not this random sample.
        delay = self.delay(record)
        return utc(record.completed_at) + timedelta(seconds=delay + int(delay * sample / 4))
