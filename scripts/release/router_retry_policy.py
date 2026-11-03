"""Shared conservative retry policy for release routers."""
from datetime import datetime, timezone
import os

MAX_ATTEMPTS = 3
COOLDOWN_SECONDS = 6 * 3600
RETRYABLE = {'failure', 'timed_out', 'startup_failure'}
NON_RETRYABLE = {'cancelled', 'action_required', 'stale', 'skipped', 'neutral'}


def requested_force_retry(environ=None):
    """Trust only an explicit manual main-branch request to bypass cooldown."""
    env = os.environ if environ is None else environ
    value = env.get('FORCE_RETRY', 'false')
    if value not in ('true', 'false'):
        raise ValueError('Invalid force_retry value')
    if value == 'true' and (env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
                            or env.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('force_retry is restricted to manual main-branch runs')
    return value == 'true'


def decide(rows, now=None, force_retry=False):
    """Return ACTIVE, SUCCESS, COOLDOWN, RETRY, or REVIEW.

    Never automatically retry cancelled/unknown outcomes; completed successes
    are terminal. force_retry bypasses only cooldown, not active/success/budget.
    The caller must supply rows for one verified build identity.
    """
    if any(r.get('status') != 'completed' for r in rows):
        return 'ACTIVE'
    if any(r.get('conclusion') == 'success' for r in rows):
        return 'SUCCESS'
    if len(rows) >= MAX_ATTEMPTS:
        return 'REVIEW'
    if any(r.get('conclusion') not in RETRYABLE for r in rows):
        return 'REVIEW'
    if not rows:
        return 'RETRY'
    now = now or datetime.now(timezone.utc)
    try:
        latest = max(datetime.fromisoformat(r['created_at'].replace('Z', '+00:00'))
                     for r in rows)
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError('Missing retry timestamp; manual review required') from error
    if latest.tzinfo is None:
        raise ValueError('Naive retry timestamp; manual review required')
    if (now - latest).total_seconds() < COOLDOWN_SECONDS and not force_retry:
        return 'COOLDOWN'
    return 'RETRY'
