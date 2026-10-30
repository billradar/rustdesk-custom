#!/usr/bin/env python3
"""Presentation-only GitHub Markdown cards. No build/recovery decisions live here."""
from contextlib import contextmanager
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import sys
import unittest

STATES = {'PASS':'✅', 'FAIL':'❌', 'WARNING':'⚠️', 'NOT RUN':'⬜', 'SKIPPED':'⏭️', 'RUNNING':'🔄'}
CHECKS = ('Patch Apply', 'Rust Compile', 'Flutter Analyze', 'Build System', 'SDK Preflight')
ALIASES = {'Rust Compile':'Rust real-config compile'}


def text(value):
    if value is None or value == '':
        return '—'
    value = ''.join(c for c in str(value) if c in '\n\r\t' or (ord(c) >= 32 and ord(c) != 127))
    value = re.sub('[\u202a-\u202e\u2066-\u2069]', '', value)
    value = html.escape(value, quote=False)
    value = re.sub(r'[\\`*_{}\[\]()#+.!|~\-]', lambda m: f'&#{ord(m.group())};', value)
    return value.replace('\r\n','\n').replace('\r','\n').replace('\n','<br>').replace('\t',' ')


def state(value):
    value = str(value or '').strip().upper()
    aliases = {'SUCCESS':'PASS','FAILURE':'FAIL','ERROR':'FAIL','CANCELLED':'SKIPPED',
               'TIMED_OUT':'FAIL','ACTION_REQUIRED':'WARNING','NEUTRAL':'WARNING',
               'IN_PROGRESS':'RUNNING','QUEUED':'NOT RUN','WAITING':'NOT RUN',
               'STARTUP_FAILURE':'FAIL','PENDING':'NOT RUN','NOT TESTED':'NOT RUN','SKIPPED BY USER':'SKIPPED'}
    return value if value in STATES else aliases.get(value, 'NOT RUN')


def analysis_status(output, exit_code):
    if exit_code:
        return 'FAIL'
    return 'WARNING' if re.search(r'^\s*warning\s*[•-]',output,re.M|re.I) else 'PASS'


def badge(value):
    value = state(value)
    return STATES[value] + ' ' + value


def table(headers, rows):
    rows = list(rows)
    return ('| ' + ' | '.join(map(text, headers)) + ' |\n| ' + ' | '.join('---' for _ in headers) + ' |\n'
            + ''.join('| ' + ' | '.join(text(cell) for cell in row) + ' |\n' for row in rows) + '\n')


def card(title, rows):
    return '### ' + text(title) + '\n\n' + table(('Field','Value'), rows)


def details(title, value):
    # JSON is escaped HTML text, so neither backticks nor closing HTML can escape it.
    raw = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if len(raw) > 16000:
        raw = raw[:16000] + '\n… truncated for display; complete evidence remains in Artifacts.'
    return '<details>\n<summary>' + text(title) + '</summary>\n\n<pre>' + html.escape(raw) + '</pre>\n\n</details>\n\n'


def overall(values):
    values = [state(x) for x in values]
    for status in ('FAIL','RUNNING','NOT RUN','WARNING','SKIPPED'):
        if status in values:
            return status
    return 'PASS' if values else 'NOT RUN'


def merge_compatibility(reports, upstream_sha=None, patchset=None):
    variants = {v:{k:'NOT RUN' for k in CHECKS} for v in ('standard','sos')}
    priority = {'NOT RUN':0,'SKIPPED':1,'PASS':2,'WARNING':3,'RUNNING':4,'FAIL':5}
    for report in reports:
        if not isinstance(report,dict):
            continue
        if report.get('simulated') or 'SIMULATED' in json.dumps(report).upper():
            continue
        if upstream_sha and report.get('upstream_sha') != upstream_sha:
            continue
        if patchset and report.get('patchset') != patchset:
            continue
        values=report.get('variants', {})
        if not isinstance(values,dict):
            continue
        for variant, checks in values.items():
            if variant not in variants or not isinstance(checks, dict):
                continue
            if report.get('Overall') == 'FAIL' and report.get('Failed variant') == variant:
                variants[variant]['Overall Compatibility'] = 'FAIL'
            if state(checks.get('Overall Compatibility')) == 'FAIL':
                variants[variant]['Overall Compatibility'] = 'FAIL'
            for key in CHECKS:
                value = state(checks.get(key, checks.get(ALIASES.get(key, ''))))
                if priority[value] > priority[variants[variant][key]]:
                    variants[variant][key] = value
    return variants


def compatibility_cards(variants, gate=None):
    output = '### 🧩 Compatibility\n\n'
    rows = []
    for label in CHECKS:
        rows.append((label, badge(variants.get('standard',{}).get(label)),badge(variants.get('sos',{}).get(label))))
    rows.append(('Overall Compatibility',*[badge(variants.get(v,{}).get('Overall Compatibility') or overall([variants.get(v,{}).get(k) for k in CHECKS])) for v in ('standard','sos')]))
    output += table(('Check','Standard','SOS'),rows)
    if gate is not None:
        output += 'Existing workflow gate: **' + badge(gate) + '**. Presentation does not change the gate.\n\n'
    output += 'Missing evidence is NOT RUN. Rust Compile covers the real configuration probe, not a full client build. SDK preflight is not executed by desktop compatibility checks.\n\n'
    return output


def duration(start, end):
    try:
        seconds = int((datetime.fromisoformat(end.replace('Z','+00:00')) - datetime.fromisoformat(start.replace('Z','+00:00'))).total_seconds())
        return f'{max(0,seconds)//60}m {max(0,seconds)%60}s'
    except (AttributeError,ValueError,TypeError):
        return None


def overview_card(run, jobs=None, upstream=None):
    upstream = upstream or {}
    known = jobs is not None
    jobs = jobs or []
    conclusion = run.get('conclusion') or run.get('status')
    ends = [j['completed_at'] for j in jobs if j.get('completed_at')]
    end = max(ends) if ends else None
    if run.get('status') != 'completed':
        end = datetime.now(timezone.utc).isoformat()
    targets = sorted({j['name'].rsplit(' / ',1)[-1] for j in jobs
                      if re.search(r'(?:android|linux|macos|windows|wayland).*(?:standard|sos)',j.get('name',''))})
    counts = [(label, sum(j.get('conclusion') in conclusions for j in jobs) if known else None)
              for label, conclusions in (('Succeeded',('success',)),('Failed',('failure','timed_out','startup_failure')),('Skipped',('skipped',)),('Cancelled',('cancelled',)))]
    return card('📊 Run overview', [
        ('Workflow',run.get('name') or run.get('display_title')),('Result',badge(conclusion)),
        ('GitHub state',conclusion),
        ('Run ID / Attempt',f'{run.get("id", "—")} / {run.get("run_attempt", "—")}'),
        ('Commit SHA',run.get('head_sha')), *counts,
        ('Wall time (including waits)',duration(run.get('created_at'),end)),
        ('Upstream version',upstream.get('upstream_version') or upstream.get('version')),
        ('Upstream SHA',upstream.get('upstream_sha')),('Build targets', '\n'.join(targets) or None)])


def recovery_card(report, maximum, current_attempt=None):
    if not report or report.get('simulated'):
        return ''
    faults = [j for j in report.get('jobs',[]) if j.get('reason') not in ('PASS','SKIPPED')]
    decision = report.get('recovery')
    intervention = ('YES' if decision == 'MANUAL_REVIEW' or any(not j.get('retry_eligible') for j in faults)
                    else 'PENDING' if decision in ('REQUESTING','REQUESTED') else 'NOT RUN' if decision == 'SKIPPED_STALE_EVENT' else 'NO' if not faults else 'YES')
    output = card('🔁 Automatic recovery',[
        ('Decision',decision),('Current attempt',current_attempt or report.get('attempt') or report.get('current_attempt')),
        ('Decision attempt',report.get('attempt') or report.get('event_attempt')),
        ('Maximum run attempts',maximum),('Maximum additional retries',maximum-1 if isinstance(maximum,int) and maximum>0 else None),
        ('Selected job',report.get('retry_job_id')),('Human intervention',intervention)])
    if faults:
        output += table(('Fault job','Category','Recovery selection'),[
            (j.get('name') or j.get('id'),j.get('reason'),
             decision if j.get('id') == report.get('retry_job_id') else 'MANUAL REVIEW' if not j.get('retry_eligible') or decision=='MANUAL_REVIEW' else 'NOT SELECTED') for j in faults])
    return output


def dashboard(run, jobs=None, upstream=None, variants=None, recovery=None, maximum=None, evidence=None):
    output = overview_card(run,jobs,upstream)
    output += compatibility_cards(variants or merge_compatibility([]))
    output += recovery_card(recovery,maximum,run.get('run_attempt'))
    repo = os.environ.get('GITHUB_REPOSITORY','')
    run_id = run.get('id')
    if re.fullmatch(r'[\w.-]+/[\w.-]+',repo) and re.fullmatch(r'[1-9][0-9]*',str(run_id or '')):
        output += f'[Full logs and Artifacts](https://github.com/{repo}/actions/runs/{run_id})\n\n'
    if evidence is not None:
        output += details('Detailed evidence',evidence)
    return output


def compatibility_report_card(report):
    if report.get('simulated'):
        return card('🧪 Simulated compatibility check',[('Production compatibility','NOT RUN'),('Result',report.get('Overall'))])
    return compatibility_cards(merge_compatibility([report])) + details('Compatibility evidence',report)


def stable_lock_card(lock):
    return card('🔒 Stable identity locked',[(key,lock.get(field)) for key,field in (
        ('Upstream version','version'),('Upstream SHA','upstream_sha'),('Commit SHA','custom_repository_sha'),
        ('Patchset','patchset'),('Build identity','build_identity'),('Wayland','wayland_included'),
        ('Signing policy','android_signing_enabled'))])


def write(key, content):
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        return False
    if not re.fullmatch(r'[a-z0-9-]+',key):
        raise ValueError('Invalid Summary section key')
    begin,end = f'<!-- rustdesk-summary:{key}:begin -->',f'<!-- rustdesk-summary:{key}:end -->'
    section = begin + '\n\n' + content + '\n' + end + '\n'
    target = Path(path)
    existing = target.read_text(encoding='utf-8') if target.exists() else ''
    pattern = re.compile(re.escape(begin)+r'.*?'+re.escape(end)+r'\n?',re.S)
    if pattern.search(existing):
        existing = pattern.sub('',existing)
    target.write_text(existing.rstrip()+'\n\n'+section, encoding='utf-8')
    return True


def publish(key, render, *args, **kwargs):
    """A renderer or Summary filesystem failure must never override a gate result."""
    if not os.environ.get('GITHUB_STEP_SUMMARY'):
        return False
    try:
        return write(key,render(*args,**kwargs))
    except Exception:
        print('Summary rendering unavailable; original build result and JSON evidence are unchanged.',file=sys.stderr)
        return False


@contextmanager
def isolated_summary():
    original = os.environ.pop('GITHUB_STEP_SUMMARY',None)
    try:
        yield
    finally:
        if original is not None:
            os.environ['GITHUB_STEP_SUMMARY'] = original
        else:
            os.environ.pop('GITHUB_STEP_SUMMARY',None)


def test_card(result, label):
    failed = len(result.failures)+len(result.errors)+len(result.unexpectedSuccesses)
    passed = result.testsRun-failed-len(result.skipped)-len(result.expectedFailures)
    output = card('🧪 '+label,[('Result',badge('PASS' if result.wasSuccessful() else 'FAIL')),
        ('Passed',passed),('Failed',failed),('Skipped',len(result.skipped)),('Expected failures',len(result.expectedFailures))])
    if result.failures or result.errors:
        output += details('Necessary failure reasons',[{'test':str(test),'reason':reason[-2000:]} for test,reason in result.failures+result.errors])
    return output


def run_contract_tests(label):
    with isolated_summary():
        program = unittest.main(exit=False)
    publish('tests-'+re.sub('[^a-z0-9-]','-',label.lower()),test_card,program.result,label)
    raise SystemExit(0 if program.result.wasSuccessful() else 1)
