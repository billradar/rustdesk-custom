"""Server ruleset canaries: only fresh owned synthetic refs, never production.

The existing IsolatedAPI remains unchanged. This separate opt-in probe permits
five deliberate rejected mutations against two newly created disposable canaries.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from .identity import canonical
from .integration import (IsolatedAPI, NAMESPACE, REPOSITORY, exercise, require,
                          trusted_context)
from .model import Record, bind, reserve
from .store import APIError, GitHubAPI, GitRefStore

BRANCH = 'coordinator/08-ref-protection-validation-20261102'
WORKFLOW = '.github/workflows/release-coordinator-protection.yml'
INDEX = 'coordinator-integration-index/v1'
RULES = {
    26375171: ('coordinator-test-journal-append-only',
               [f'refs/heads/{NAMESPACE}/{c}/*' for c in ('stable', 'nightly')],
               {'deletion', 'non_fast_forward'}),
    26375414: ('coordinator-test-run-index-immutable',
               [f'refs/heads/{INDEX}/*'], {'deletion', 'non_fast_forward', 'update'}),
}


def verify_rules(api, repository):
    """Fail closed before creating resources if the reviewed mirror rules drift."""
    visibility = {}
    for identifier, (name, includes, kinds) in RULES.items():
        rule = api.request('GET', f'repos/{repository}/rulesets/{identifier}')
        require(rule.get('name') == name and rule.get('target') == 'branch'
                and rule.get('enforcement') == 'active'
                and ('bypass_actors' not in rule or rule['bypass_actors'] == [])
                and rule.get('conditions') == {'ref_name': {'include': includes, 'exclude': []}},
                'Mirror ruleset scope/enforcement/bypass drift')
        visibility[str(identifier)] = 'visible_empty' if 'bypass_actors' in rule else 'not_exposed_to_token'
        rows = rule.get('rules', [])
        require(len(rows) == len(kinds) and {r['type'] for r in rows} == kinds,
                'Mirror ruleset rule drift')
        for row in rows:
            require(row.get('parameters', {}) in ({}, {'update_allows_fetch_and_merge': False}),
                    'Unexpected ruleset parameters')
    return visibility


class Canaries:
    """Negative probes accept only owned refs and the two known state commits."""
    def __init__(self, raw, repository, journal, root, child, index):
        require(journal.startswith('heads/'+NAMESPACE+'/stable/')
                and re.fullmatch('heads/'+NAMESPACE+r'/stable/[0-9a-f]{64}', journal)
                and re.fullmatch('heads/'+INDEX+r'/[0-9a-f]{64}', index), 'Unsafe canary ref')
        require(all(re.fullmatch('[0-9a-f]{40}', s) for s in (root, child)) and root != child,
                'Invalid canary history')
        self.raw, self.base = raw, f'repos/{repository}/git/'
        self.journal, self.root, self.child, self.index = journal, root, child, index
        self.owned = set()
        self.rejections = []

    def read(self, ref):
        require(ref in (self.journal, self.index), 'Unknown canary')
        row = self.raw.request('GET', self.base+'ref/'+ref)
        require(row.get('ref') == 'refs/'+ref and row['object'].get('type') == 'commit',
                'Unexpected canary ref evidence')
        return row['object']['sha']

    def adopt_created_journal(self):
        # Caller created this unpredictable ref with the unmodified store.
        require(self.read(self.journal) == self.child, 'Journal positive control missing')
        self.owned.add(self.journal)

    def create_index(self):
        try:
            self.read(self.index)
        except APIError as error:
            if error.status != 404:
                raise
        else:
            raise ValueError('Never adopt an existing index')
        self.raw.request('POST', self.base+'refs', {'ref': 'refs/'+self.index, 'sha': self.root})
        require(self.read(self.index) == self.root, 'Index creation positive control failed')
        self.owned.add(self.index)

    def reject(self, label, ref, method, sha=None, force=False):
        allowed = {(self.journal, 'PATCH', self.root, True),
                   (self.journal, 'DELETE', None, False),
                   (self.index, 'PATCH', self.child, False),
                   (self.index, 'PATCH', self.child, True),
                   (self.index, 'DELETE', None, False)}
        require(ref in self.owned and (ref, method, sha, force) in allowed,
                'Probe outside owned canary operations')
        expected = self.child if ref == self.journal else self.root
        require(self.read(ref) == expected, 'Canary changed before probe')
        data = {'sha': sha, 'force': force} if method == 'PATCH' else None
        try:
            self.raw.request(method, self.base+'refs/'+ref, data)
        except APIError as error:
            # 401/403/429/5xx and unknown outcomes never masquerade as protection.
            require(error.status == 422, 'Expected explicit Git ref policy rejection (422)')
        else:
            raise AssertionError('Server accepted forbidden canary mutation')
        require(self.read(ref) == expected, 'Rejected mutation changed the canary')
        self.rejections.append({'check': label, 'status': 422, 'unchanged': True})


def protection_exercise(raw, repository, session):
    bypass_visibility = verify_rules(raw, repository)
    api = IsolatedAPI(raw, repository)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    key = hashlib.sha256((session+':journal-canary').encode()).hexdigest()
    record = Record('stable', key, 'a'*40, now, canonical({'fixture':'protection','session':session}).decode())
    journal = GitRefStore(api, repository, 'stable', key, namespace=NAMESPACE)
    api.register(journal.ref)
    event = reserve(record, str(uuid4()), now, now+timedelta(hours=1))
    root = journal.append(event, None)
    child = journal.append(bind(root.record, root.record.reservation_id, root.record.fence, '101', now), root)
    index = 'heads/'+INDEX+'/'+hashlib.sha256((session+':index-canary').encode()).hexdigest()
    probes = Canaries(raw, repository, journal.ref, root.sha, child.sha, index)
    probes.adopt_created_journal()
    probes.create_index()
    probes.reject('journal_non_fast_forward', journal.ref, 'PATCH', root.sha, True)
    probes.reject('journal_deletion', journal.ref, 'DELETE')
    probes.reject('index_fast_forward', index, 'PATCH', child.sha)
    probes.reject('index_forced_update', index, 'PATCH', child.sha, True)
    probes.reject('index_deletion', index, 'DELETE')
    races = exercise(IsolatedAPI(raw, repository), repository, session+':protected-races')
    return dict(schema_version=1, result='PASS', session=session, ruleset_ids=list(RULES),
                bypass_visibility=bypass_visibility,
                positive_controls=['journal_create','journal_fast_forward','index_create'],
                rejections=probes.rejections, protected_storage=races,
                refs=['refs/'+journal.ref, 'refs/'+index]+races['refs'],
                limitation='Synthetic Git state only; no production state, build, signing or publication')


def main():
    repository = trusted_context(branch=BRANCH, workflow_path=WORKFLOW)
    session = os.environ['GITHUB_RUN_ID']+'-'+str(uuid4())
    result = dict(schema_version=1, result='FAIL', session=session)
    try:
        result = protection_exercise(GitHubAPI(), repository, session)
    except Exception as error:
        result['failure_type'] = type(error).__name__
        raise
    finally:
        path = Path('.work/coordinator-protection/summary.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
        print(json.dumps(result, sort_keys=True))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                stream.write('## Isolated ref protection verification\n\n```json\n'+json.dumps(result, indent=2)+'\n```\n')


if __name__ == '__main__':
    main()
