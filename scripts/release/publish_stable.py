"""Manual immutable publication of one already-qualified Stable Draft. No builds."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

from scripts.release import attestation
from scripts.release.github import request
from scripts.upstream.resolve import api

REPOSITORY = attestation.REPOSITORY
WORKFLOW = 'publish-stable.yml'


def context():
    expected = dict(GITHUB_REPOSITORY=REPOSITORY, GITHUB_REF='refs/heads/main',
                    GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_ACTOR='billradar',GITHUB_ACTOR_ID=attestation.OWNER_ID,
                    GITHUB_WORKFLOW_REF=f'{REPOSITORY}/.github/workflows/{WORKFLOW}@refs/heads/main')
    if (any(os.environ.get(k) != v for k, v in expected.items())
            or os.environ.get('GITHUB_TRIGGERING_ACTOR','billradar')!='billradar'):
        raise ValueError('Stable publication requires the owner-manually dispatched main publisher workflow')


def identity_inputs(release_id, tag, manifest_sha256):
    if (not re.fullmatch(r'[1-9][0-9]*',str(release_id))
            or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-custom\.v[1-9][0-9]*\.[1-9][0-9]{0,5}',tag)
            or not re.fullmatch('[0-9a-f]{64}',manifest_sha256)):
        raise ValueError('Exact Release ID, Stable tag and manifest SHA256 are required')
    if tag == 'v1.5.1-custom.v2.8':
        raise ValueError('Protected historical 1.5.1 v2 revision 8 cannot be published by this workflow')


def snapshot(release):
    return {k:release.get(k) for k in ('id','name','tag_name','target_commitish','draft',
                                      'prerelease','immutable','updated_at','assets')}


def check_draft(release_id,tag,digest,allow_published=False):
    release=api(f'repos/{REPOSITORY}/releases/{release_id}')
    if (release.get('id')!=int(release_id) or not (release.get('draft') is True or (allow_published and release.get('draft') is False and release.get('immutable') is True))
            or release.get('prerelease') is not False or (release.get('draft') is True and release.get('immutable') is True)
            or (release.get('tag_name')!=tag and release.get('name')!=tag)):
        raise ValueError('Selected object is not the expected Stable Draft or immutable published Release')
    rows=[a for a in release.get('assets',[]) if a.get('name')==attestation.MANIFEST]
    if len(rows)!=1 or rows[0].get('digest')!='sha256:'+digest:
        raise ValueError('Selected Draft manifest differs from the manually pinned digest')
    value=attestation.read_release(release,'stable',tag=tag)
    attestation.require_production_signing(value)
    from scripts.upstream.patchsets import require_selection
    from scripts.upstream.patchset_version import current
    require_selection(value['upstream_version'],value['patchset'],channel='stable')
    metadata=current(value['patchset'])
    revision=int(value['patch_revision'].rsplit('.',1)[1])
    entries=[e for e in metadata['versioning']['history'] if e['revision']==revision]
    if len(entries)!=1 or entries[0]['after']!={'common':value['common_patch_hash'],'sos':value['sos_patch_hash']}:
        raise ValueError('Draft content is not in the reviewed immutable patch revision history')
    from scripts.release.stable_tag import commit_of
    ref=api(f'repos/{REPOSITORY}/git/ref/tags/{tag}',missing=True)
    if not ref or commit_of(REPOSITORY,ref)!=value['custom_repository_sha']:
        raise ValueError('Stable Git tag differs from attested custom source; publisher never creates or moves tags')
    run=api(f'repos/{REPOSITORY}/actions/runs/{value["build_run"]}')
    if (run.get('status')!='completed' or run.get('conclusion')!='success'
            or run.get('head_branch')!='main' or run.get('event')!='workflow_dispatch'
            or run.get('path')!='.github/workflows/tag.yml'
            or run.get('head_sha')!=value['custom_repository_sha']):
        raise ValueError('Draft must come from a successful protected-main Stable build')
    return release,value


def native_statement(result,release,value,tag):
    """Additional binding on the maintained gh verifier's cryptographic result."""
    verified=result.get('verificationResult',{})
    cert=verified.get('signature',{}).get('certificate',{})
    if cert.get('subjectAlternativeName')!='https://dotcom.releases.github.com':
        raise ValueError('Native proof has an unexpected GitHub release signer')
    statement=verified.get('statement',{})
    predicate=statement.get('predicate',{})
    if (statement.get('_type')!='https://in-toto.io/Statement/v1'
            or statement.get('predicateType')!='https://in-toto.io/attestation/release/v0.2'):
        raise ValueError('Native proof is not a Release v0.2 statement')
    wanted=dict(databaseId=str(release['id']),ownerId=attestation.OWNER_ID,
                repositoryId=attestation.REPOSITORY_ID,packageId=attestation.REPOSITORY_ID,
                repository=REPOSITORY,tag=tag,purl=f'pkg:github/{REPOSITORY}@{tag}')
    if any(predicate.get(k)!=v for k,v in wanted.items()):
        raise ValueError('Native proof release/repository/owner/tag identity mismatch')
    ref=api(f'repos/{REPOSITORY}/git/ref/tags/{tag}')
    from scripts.release.stable_tag import commit_of
    if commit_of(REPOSITORY,ref)!=value['custom_repository_sha']:
        raise ValueError('Native publication tag no longer identifies the expected commit')
    subjects=statement.get('subject',[])
    expected={a['name']:a['digest'][7:] for a in release['assets']}
    files={};refs=[]
    for subject in subjects:
        if subject.get('uri')==wanted['purl']:
            refs.append(subject)
        elif subject.get('name') in expected and subject['name'] not in files:
            files[subject['name']]=subject.get('digest',{}).get('sha256')
        else:
            raise ValueError('Native proof has an unexpected or duplicate subject')
    if (files!=expected or len(refs)!=1
            or refs[0].get('digest')!={'sha1':ref.get('object',{}).get('sha')}):
        raise ValueError('Native proof does not cover the exact Git object and complete asset inventory')
    return statement


def publish(release_id,tag,digest,output=Path('.work/stable-publication.json')):
    context();identity_inputs(release_id,tag,digest)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    receipt=dict(release_id=int(release_id),tag=tag,manifest_sha256=digest,
                 publication='NOT ATTEMPTED',native_attestation='NOT VERIFIED')
    def record():output.write_text(json.dumps(receipt,indent=2)+'\n')
    record()
    # Read-only administration permission; this workflow never enables the setting.
    settings=api(f'repos/{REPOSITORY}/immutable-releases')
    if settings.get('enabled') is not True:
        raise ValueError('Repository immutable releases must already be enabled before manual publication')
    for args in (['gh','release','verify','--help'],['gh','attestation','verify','--help']):
        subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=30)
    release,value=check_draft(release_id,tag,digest,allow_published=True)
    # A second complete proof/inventory check rejects changes during preflight.
    fresh,fresh_value=check_draft(release_id,tag,digest,allow_published=True)
    if snapshot(fresh)!=snapshot(release) or fresh_value!=value:
        raise ValueError('Draft changed during publication preflight; no write performed')
    if release['draft']:
        receipt['publication']='REQUESTING';record()
        try:
            # Exactly one publication request; never retry an ambiguous write.
            final=request('PATCH',f'repos/{REPOSITORY}/releases/{release_id}',
                          dict(tag_name=tag,target_commitish=value['custom_repository_sha'],draft=False,prerelease=False))
        except Exception:
            receipt['publication']='UNKNOWN; inspect Release state before any retry';record();raise
        receipt['publication']='PUBLISHED' if final.get('draft') is False else 'UNEXPECTED STATE';record()
    else:
        final=release
        receipt['publication']='ALREADY PUBLISHED; READ-ONLY VERIFICATION';record()
    if (final.get('id')!=int(release_id) or final.get('draft') is not False
            or final.get('prerelease') is not False or final.get('tag_name')!=tag
            or final.get('immutable') is not True):
        raise ValueError('Publication response is not the expected immutable Stable Release; inspect receipt')
    for attempt in range(10):
        # Native proof is generated by GitHub AFTER publication; only reads retry.
        try:
            current_release=api(f'repos/{REPOSITORY}/releases/{release_id}')
            fields=('id','name','size','digest','state')
            inventory=lambda r:sorted([{k:a.get(k) for k in fields} for a in r.get('assets',[])],key=lambda a:a['id'])
            # Draft download aliases change on publication; asset identities do not.
            if (current_release.get('id')!=int(release_id) or current_release.get('draft') is not False
                    or current_release.get('immutable') is not True or current_release.get('prerelease') is not False
                    or current_release.get('tag_name')!=tag or inventory(current_release)!=inventory(release)):
                receipt['native_attestation']='INVALID AFTER PUBLICATION';record()
                raise ValueError('Published identity or asset inventory changed')
            result=subprocess.run(['gh','release','verify',tag,'--repo',REPOSITORY,'--format','json'],
                                  check=True,capture_output=True,text=True,timeout=120)
            try:
                statement=native_statement(json.loads(result.stdout,object_pairs_hook=attestation._object),current_release,value,tag)
            except (ValueError,TypeError,KeyError):
                receipt['native_attestation']='INVALID AFTER PUBLICATION';record();raise
            receipt.update(native_attestation='VERIFIED',statement=statement);record()
            return receipt
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
            if attempt==9:break
            time.sleep(10)
        except Exception:
            if receipt['native_attestation']!='INVALID AFTER PUBLICATION':
                receipt['native_attestation']='FAILED AFTER PUBLICATION'
            record();raise
    receipt['native_attestation']='FAILED AFTER PUBLICATION';record()
    raise ValueError('Release is already published; native proof could not be verified. Do not rebuild, delete or republish it.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release-id',required=True)
    p.add_argument('--tag',required=True)
    p.add_argument('--manifest-sha256',required=True)
    args=p.parse_args();publish(args.release_id,args.tag,args.manifest_sha256)
