"""Read-only capture and offline PR preparation; no production state importer."""
import argparse
import hashlib
import json
from pathlib import Path

from .identity import canonical
from .legacy import (AUDIT_SHA256, REPOSITORY, Catalog, audited_rows, fingerprint,
                     identity, load, require, source_hint)
from .reconcile import COMPILE_STEPS
from .store import GitHubAPI


class ReadOnlyAPI:
    def __init__(self, api):
        self.api = api

    def request(self, method, path, data=None):
        require(method == 'GET' and data is None
                and path.startswith('repos/'+REPOSITORY+'/actions/runs/'), 'Legacy capture is read-only')
        return self.api.request(method, path)


def observe(api, row):
    api = ReadOnlyAPI(api)
    base = f"repos/{REPOSITORY}/actions/runs/{row['run_id']}"
    before = api.request('GET', base)
    attempts = []
    for attempt in range(1, row['latest_attempt']+1):
        jobs = [];total = None
        for page in range(1, 101):
            result = api.request('GET', f'{base}/attempts/{attempt}/jobs?per_page=30&page={page}')
            batch = result['jobs']
            require(total is None or result['total_count'] == total, 'Jobs changed during capture')
            total = result['total_count'];jobs.extend(batch)
            if len(batch) < 30:
                break
        else:
            raise ValueError('Historical jobs pagination exhausted')
        require(len(jobs) == total and len({j['id'] for j in jobs}) == len(jobs)
                and all(j['run_id'] == row['run_id'] and type(j['run_attempt']) is int
                        and j['run_attempt'] == attempt and j['status'] == 'completed' for j in jobs),
                'Incomplete, active or foreign job inventory')
        steps = []
        for job in jobs:
            for step in job.get('steps') or []:
                if step.get('name') in COMPILE_STEPS and step.get('conclusion') not in (None, 'skipped','neutral'):
                    steps.append(dict(job_id=job['id'], **{k:step.get(k) for k in
                        ('name','status','conclusion','started_at','completed_at')}))
        attempts.append(dict(attempt=attempt, job_count=len(jobs),
                             jobs_sha256=hashlib.sha256(canonical(jobs)).hexdigest(), compile_steps=steps))
    after = api.request('GET', base)
    require(fingerprint(before) == fingerprint(after), 'Run changed during capture')
    return dict(run=fingerprint(after), attempts=attempts)


def capture(api):
    records = []
    for row in audited_rows().values():
        records.append(dict(audit_row=row, observation=observe(api, row)))
    records.sort(key=lambda r:(r['audit_row']['channel'], r['audit_row']['run_id']))
    Catalog(records)
    return records


def prepare(records, directory):
    """Atomic Git commit/PR is the installation unit; partial files fail closed.

    Concurrent PR imports fork the content-addressed chain and cannot be silently
    union-merged. Regenerate from the current reviewed tip; never overwrite rows.
    """
    catalog = Catalog(records)
    directory = Path(directory)
    if (directory/'head.pending').exists():
        resume(directory)
    previous = ''
    if directory.exists() and any(directory.iterdir()):
        existing = load(directory)
        previous = json.loads((directory/'head.json').read_text())['catalog_sha256']
        require(all(catalog.records.get(k) == v for k,v in existing.records.items()),
                'Cannot delete or replace archived evidence')
        if catalog.records == existing.records:
            return previous  # Idempotent import emits no new object.
    value = dict(schema_version=1, kind='legacy-dedup-catalog', repository=REPOSITORY,
                 source_audit_sha256=AUDIT_SHA256, previous_catalog_sha256=previous,
                 records=sorted(records,key=lambda r:(r['audit_row']['channel'], r['audit_row']['run_id'])))
    raw = canonical(value);key = hashlib.sha256(raw).hexdigest()
    target = directory/'objects'/(key+'.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    # Immutable content objects never overwrite an existing path.
    if target.exists():
        require(target.read_bytes() == raw, 'Existing legacy object conflict')
    else:
        with target.open('xb') as stream:stream.write(raw)
    head = canonical(dict(schema_version=1,catalog_sha256=key))
    temporary = directory/'head.pending'
    with temporary.open('xb') as stream:stream.write(head)
    temporary.replace(directory/'head.json')
    load(directory)
    return key


def resume(directory):
    """Recover offline preparation only after validating the complete new chain.

    An incomplete/missing object stays blocked. Never delete/repair a production
    journal. Installation remains one reviewed Git commit with entries intact.
    """
    directory = Path(directory)
    temporary = directory/'head.pending'
    require(temporary.is_file() and not temporary.is_symlink(), 'Missing/nonregular pending catalog head')
    load(directory, pending_head=temporary.read_bytes())
    temporary.replace(directory/'head.json')
    return load(directory)


def summary(records):
    rows = [r['audit_row'] for r in records]
    return dict(schema_version=1, repository=REPOSITORY, records=len(rows),
        success_holds=sum(identity(r) is not None for r in rows),
        review_holds=sum(identity(r) is None for r in rows),
        no_build_rows=sum(not r['observed_compile_attempts'] for r in rows),
        actual_compile_attempts=sum(len(r['observed_compile_attempts']) for r in rows),
        missing_source_holds=sum(not source_hint(r) for r in rows),
        production_state_written=False, automatic_retry_authorized=False,
        installation='Review a single Git commit/PR; quiesce and reconcile before cutover')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('capture','prepare','check'))
    parser.add_argument('--observations',type=Path)
    parser.add_argument('--directory',type=Path)
    args = parser.parse_args()
    if args.mode == 'capture':
        require(args.observations is not None, 'Capture output path required')
        records = capture(GitHubAPI())
        with args.observations.open('x') as stream:stream.write(canonical(records).decode())
        print(json.dumps(summary(records),sort_keys=True))
    elif args.mode == 'prepare':
        require(args.observations is not None and args.directory is not None, 'Input and output paths required')
        records = json.loads(args.observations.read_bytes())
        key = prepare(records,args.directory)
        print(json.dumps(dict(summary(records),catalog_sha256=key),sort_keys=True))
    else:
        require(args.directory is not None, 'Catalog directory required')
        catalog = load(args.directory)
        print(json.dumps(summary(list(catalog.records.values())),sort_keys=True))


if __name__ == '__main__':
    main()
