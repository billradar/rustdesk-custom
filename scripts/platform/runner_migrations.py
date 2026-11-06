"""Explicit, fail-closed aliases from retired official runners to supported images."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
POLICY=ROOT/'metadata/platform/runner-migrations.json'
KEYS={'platform','architecture','source_runner','runner','reason'}


def migrations():
    data=json.loads(POLICY.read_text())
    if set(data)!={'schema_version','migrations'} or data['schema_version']!=1 or type(data['migrations']) is not list:
        raise ValueError('BUILD_COMPAT: unknown runner migration policy')
    seen=set()
    for item in data['migrations']:
        if set(item)!=KEYS or any(type(item[k]) is not str or not item[k] for k in KEYS):
            raise ValueError('BUILD_COMPAT: malformed runner migration')
        key=(item['platform'],item['architecture'])
        if key in seen or item['source_runner']==item['runner']:
            raise ValueError('BUILD_COMPAT: duplicate or ineffective runner migration')
        seen.add(key)
    return data['migrations']


def effective_runner(platform, architecture, source_runner):
    rows=[m for m in migrations() if m['platform']==platform and m['architecture']==architecture]
    if not rows:
        return source_runner
    migration=rows[0]
    if source_runner!=migration['source_runner']:
        return source_runner
    return migration['runner']


def validates_matrix_runner(platform, architecture, matrix_runner, reviewed_profiles):
    if any(p['platform']==platform and p['architecture']==architecture and p['runner']==matrix_runner
           for p in reviewed_profiles):
        return True
    for migration in migrations():
        if (migration['platform']==platform and migration['architecture']==architecture
                and migration['runner']==matrix_runner
                and any(p['platform']==platform and p['architecture']==architecture
                        and p['runner']==migration['source_runner'] for p in reviewed_profiles)):
            return True
    return False
