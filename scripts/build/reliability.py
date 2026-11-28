"""Bounded, operation-specific dependency recovery for the shared build core."""

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import random
import re
import selectors
import signal
import subprocess
import sys
import time

POLICY = Path(__file__).resolve().parents[2] / 'metadata/build/reliability-policy.json'
MAVEN = 'android-flutter-apk'
GIT = 'upstream-fetch'
CARGO = 'mac-intel-cargo-fetch'
NETWORK = {
    'NET_CONNECT_FAILED': r"Failed to connect to github\.com port 443[^\n]*Couldn't connect to server",
    'NET_CONNECT_TIMEOUT': r'(?:Failed to connect to github\.com port 443[^\n]*Timeout was reached|Connection timed out after [0-9]+ milliseconds)',
    'NET_READ_TIMEOUT': r'Operation timed out after [0-9]+ milliseconds with [0-9]+ (?:out of [0-9]+ )?bytes received',
    'NET_CONNECTION_RESET': r'(?:Recv failure: Connection reset by peer|Connection reset by peer)',
    'NET_DNS_TEMPORARY': r'Temporary failure in name resolution',
    'NET_SERVER_ERROR': r'The requested URL returned error: (?:408|502|503|504)\b',
}
ALLOWED = {MAVEN: {'NET_RATE_LIMIT'}, GIT: set(NETWORK), CARGO: set(NETWORK)}
HARD_FAILURE = re.compile(
    r'checksum|hash mismatch|signature verification failed|certificate problem|'
    r'certificate verify failed|authentication failed|permission denied|'
    r'could not read Username|(?:returned error:|received status code) (?:401|403|404)\b|'
    r'repository not found|no space left on device|out of memory|'
    r'lock file .* needs to be updated|revision .* not found|'
    r'patch does not apply|(?:PATCH|BUILD)_COMPAT:|'
    r'PROVENANCE:|SIGNING:|could not compile|compilation failed|'
    r"execution failed for task (?!':gradle:compileGroovy')|test failed", re.IGNORECASE,
)
MAVEN_429 = re.compile(
    r"Could not (?:GET|HEAD) 'https://repo\.maven\.apache\.org/maven2/"
    r"(?:com/squareup/javawriter/2\.5\.0/javawriter-2\.5\.0|org/ow2/asm/asm/9\.1/asm-9\.1)"
    r"\.(?:jar|pom)'\. Received status code 429 from server(?::|\s|$)"
)
GIT_REMOTE = re.compile(r"https://github\.com/rustdesk/rustdesk(?:\.git|/)")
SCITER_REMOTE = re.compile(r"https://github\.com/rustdesk-org/rust-sciter(?:\.git|/|['\s]|$)")
CLEANUP_SECONDS = 3


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate reliability policy key')
        result[key] = value
    return result


def load_policy(path=POLICY):
    data = json.loads(path.read_text(), object_pairs_hook=unique_object)
    if (not isinstance(data, dict) or set(data) != {'schema', 'operations'}
            or data['schema'] != 'build-reliability-policy-v1'
            or not isinstance(data['operations'], dict) or set(data['operations']) != set(ALLOWED)):
        raise ValueError('Invalid build reliability policy')
    for operation, rule in data['operations'].items():
        if not isinstance(rule, dict) or set(rule) != {'delays', 'budget_seconds', 'categories'}:
            raise ValueError('Invalid operation policy')
        delays, budget, categories = rule['delays'], rule['budget_seconds'], rule['categories']
        if (not isinstance(delays, list) or len(delays) > (1 if operation == MAVEN else 3)
                or any(type(delay) is not int or not 1 <= delay <= 240 for delay in delays)
                or delays != sorted(set(delays))
                or type(budget) is not int or not 10 <= budget <= 7200
                or not isinstance(categories, list) or any(type(item) is not str for item in categories)
                or len(categories) != len(set(categories)) or not set(categories) <= ALLOWED[operation]):
            raise ValueError('Invalid operation policy limits')
    return data['operations']


def mode():
    value = os.environ.get('BRF_MODE', 'observe')
    if value not in {'off', 'observe', 'canary'}:
        raise ValueError('Invalid BRF_MODE')
    if value == 'canary' and (os.environ.get('BUILD_CHANNEL') != 'ci' or os.name != 'posix'):
        raise ValueError('BRF canary requires a POSIX CI fixture')
    if os.name != 'posix':
        return 'off'
    return value


def classify(operation, code, log, hard_failure=False):
    if code <= 0 or hard_failure or HARD_FAILURE.search(log):
        return 'CANCELLED' if code < 0 else 'UNKNOWN'
    if operation == MAVEN:
        if (re.search(r"Could not resolve all (?:files|artifacts) for configuration ':gradle:compileClasspath'", log)
                and MAVEN_429.search(log)):
            return 'NET_RATE_LIMIT'
    elif ((operation == GIT and GIT_REMOTE.search(log))
          or (operation == CARGO and SCITER_REMOTE.search(log) and 'failed to fetch' in log)):
        for category, pattern in NETWORK.items():
            if re.search(pattern, log):
                return category
    return 'UNKNOWN'


def retry_after(value, now):
    """Parse a structured response header, when the calling tool exposes one."""
    if value is None:
        return 0
    value = value.strip()
    if re.fullmatch(r'[0-9]+', value):
        # Large valid values exceed any operation budget.
        return float('inf') if len(value.lstrip('0')) > 9 else int(value.lstrip('0') or '0')
    try:
        date = parsedate_to_datetime(value)
        return 0 if date.tzinfo is None else max(0, (date - now).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0


def retry_delay(seconds, remaining, header=None):
    delay = max(seconds * random.uniform(1, 1.2), retry_after(header, datetime.now(timezone.utc)))
    return delay if delay + CLEANUP_SECONDS < remaining else None


class Interrupted(Exception):
    def __init__(self, signum):
        self.signum = signum


def interrupt(signum, _frame):
    raise Interrupted(signum)


def stop_group(process):
    # Even if the leader exited, descendants may still hold the log pipe.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=CLEANUP_SECONDS)


def execute(argv, cwd, env, deadline):
    tail = b''
    pending = b''
    hard_failure = False
    with selectors.DefaultSelector() as selector:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                timeout = None if deadline is None else max(0, deadline - time.monotonic())
                if timeout == 0 or not selector.select(timeout):
                    raise subprocess.TimeoutExpired(argv, timeout)
                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                tail = (tail + chunk)[-131072:]
                parts = (pending + chunk).split(b'\n')
                pending = parts.pop()
                if len(pending) > 16384:
                    hard_failure = True
                    pending = b''
                hard_failure |= any(HARD_FAILURE.search(line.decode(errors='replace')) is not None for line in parts)
            timeout = None if deadline is None else max(0, deadline - time.monotonic())
            hard_failure |= HARD_FAILURE.search(pending.decode(errors='replace')) is not None
            return process.wait(timeout=timeout), tail.decode(errors='replace'), hard_failure
        except BaseException:
            stop_group(process)
            raise
        finally:
            process.stdout.close()


def event(operation, attempt, category, result, start, deadline, code=None, delay=None):
    now = time.monotonic()
    data = dict(schema='build-reliability-event-v1', operation=operation, operation_attempt=attempt,
                category=category, result=result, elapsed_seconds=round(now - start, 2),
                budget_remaining_seconds=None if deadline is None else round(max(0, deadline - now), 2),
                exit_code=code, retry_delay_seconds=delay)
    print('BRF ' + json.dumps(data, separators=(',', ':')), flush=True)


def run(operation, argv, cwd, *, env=None, replay_safe=lambda: True):
    active = mode()
    if operation not in ALLOWED:
        raise ValueError('Unknown reliability operation')
    if active == 'off':
        return subprocess.call(argv, cwd=cwd, env=env)
    rule = load_policy()[operation]
    start = time.monotonic()
    end = start + rule['budget_seconds'] if active == 'canary' else None
    delays = rule['delays'] if end is not None else []
    handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    attempt = 1
    previous = None
    try:
        for attempt in range(1, len(delays) + 2):
            if previous is not None:
                event(operation, attempt, previous, 'RETRY_STARTED', start, end)
            code, log, hard = execute(argv, cwd, env, None if end is None else end - CLEANUP_SECONDS)
            if code == 0:
                if previous is not None:
                    event(operation, attempt, previous, 'RECOVERED', start, end, code)
                return code
            category = classify(operation, code, log, hard)
            eligible = category in rule['categories'] and replay_safe()
            delay = (retry_delay(delays[attempt - 1], end - time.monotonic())
                     if eligible and attempt <= len(delays) else None)
            if delay is None:
                result = 'CANCELLED' if code < 0 else 'OBSERVED' if end is None else 'EXHAUSTED' if eligible else 'FAILED'
                event(operation, attempt, category, result, start, end, code)
                return code
            event(operation, attempt, category, 'RETRY_SCHEDULED', start, end, code, delay)
            previous = category
            time.sleep(delay)
    except subprocess.TimeoutExpired:
        event(operation, attempt, 'DEADLINE_EXCEEDED', 'EXHAUSTED', start, end, 124)
        return 124
    except Interrupted as error:
        event(operation, attempt, 'CANCELLED', 'CANCELLED', start, end, -error.signum)
        return -error.signum
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def exit_code(code):
    return 128 - code if code < 0 else code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fetch the reviewed upstream remote')
    parser.add_argument('destination', type=Path)
    parser.add_argument('ref')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', args.ref):
        parser.error('Invalid upstream ref')
    command = ['git', 'fetch', '--depth=1', 'https://github.com/rustdesk/rustdesk.git', args.ref]
    sys.exit(exit_code(run(GIT, command, args.destination)))
