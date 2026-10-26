#!/usr/bin/env python3
"""Stable upstream router: only dispatch trusted main drafts, bounded retries."""
import os,re,subprocess
from scripts.upstream.resolve import api,choose_stable
from scripts.upstream.patchsets import patchset_for_version,patch_hash
from scripts.release.channel import build_identity,release_rows

REPO='billradar/rustdesk-custom'

def state(rows,tag,sha):
    selected=[r for r in rows if r.get('display_title')==f'Stable {tag} / draft' and r.get('head_sha')==sha and r.get('head_branch')=='main' and r.get('event')=='workflow_dispatch']
    if any(r.get('status')!='completed' for r in selected):return 'ACTIVE'
    return 'EXHAUSTED' if len(selected)>=3 else 'RETRY'

def existing(release):
    version=release['version']; patchset=patchset_for_version(version)
    identity=build_identity(release['upstream_sha'],patchset,patch_hash('common',patchset),patch_hash('sos',patchset))
    for row in release_rows(version):
        body=row.get('body') or ''
        if re.search(r'^(?:Build Identity: |build_identity=)'+identity+r'$',body,re.M):
            if (f'Upstream SHA: {release["upstream_sha"]}' not in body or row.get('prerelease')
                or not ('Automation-State: complete' in body or 'automation_state=complete' in body)
                or not any(a.get('name')=='SHA256SUMS' and a.get('state')=='uploaded' for a in row.get('assets',[]))):
                raise ValueError('Existing Stable release is incomplete; manual review required')
            return True
    return False

def route():
    if (os.getenv('GITHUB_REPOSITORY')!=REPO or os.getenv('GITHUB_REF')!='refs/heads/main'
        or os.getenv('GITHUB_EVENT_NAME') not in ('schedule','workflow_dispatch')
        or not re.fullmatch(r'[0-9a-f]{40}',os.getenv('GITHUB_SHA',''))):
        raise ValueError('Untrusted Stable router context')
    release=choose_stable()
    if existing(release):
        print('Verified Stable draft/release exists; skip')
        return
    tag=release['upstream_tag'];rows=[]
    for page in range(1,11):
        batch=api(f'repos/{REPO}/actions/workflows/tag.yml/runs?event=workflow_dispatch&branch=main&per_page=100&page={page}')['workflow_runs']
        rows.extend(batch)
        if len(batch)<100:break
    else:raise ValueError('Run history exhausted; fail closed')
    current=state(rows,tag,os.environ['GITHUB_SHA'])
    if current=='ACTIVE':return
    if current=='EXHAUSTED':raise ValueError('Three attempts failed to produce a verified Stable draft')
    subprocess.run(['gh','workflow','run','tag.yml','--repo',REPO,'--ref','main',
                    '-f','upstream_ref='+tag,'-f','release_mode=draft','-f','include_wayland=true'],check=True)

if __name__=='__main__':route()
