"""Explicit credential-free formal validation context; never authorizes releases."""
import hashlib
import os
import re
from scripts.build import recipe_admission

def require(ok,message):
    if not ok:
        raise ValueError('FORMAL_VALIDATION: '+message)

def context(sha):
    require(os.environ.get('GITHUB_ACTIONS')=='true' and
            os.environ.get('GITHUB_REPOSITORY')=='billradar/rustdesk-custom' and
            os.environ.get('GITHUB_EVENT_NAME') in ('pull_request','workflow_dispatch') and
            os.environ.get('BUILD_CHANNEL')=='ci' and
            os.environ.get('BUILD_CONFIGURATION')=='TEST ONLY' and
            os.environ.get('PATCHSET')=='v4' and
            os.environ.get('UPSTREAM_EXPECTED_SHA')==sha and
            os.environ.get('CLIENT_RELEASE_IDENTITY','false')=='false' and
            not os.environ.get('CLIENT_PATCH_REVISION') and
            not os.environ.get('BUILD_FLAVOR') and
            re.fullmatch(r'[0-9a-f]{40}',os.environ.get('GITHUB_SHA','')) and
            re.fullmatch(r'[1-9][0-9]*',os.environ.get('GITHUB_RUN_ID','')),
            'isolated CI-only dry-run context required')
    recipe_admission.source(sha)
    return {'schema':'formal-prepared-source-v1','release_eligible':False,
            'configuration':'TEST ONLY','upstream_sha':sha,
            'custom_repository_sha':os.environ['GITHUB_SHA'],
            'workflow_run':os.environ['GITHUB_RUN_ID'],
            'admission_sha256':hashlib.sha256(recipe_admission.POLICY.read_bytes()).hexdigest()}

def verify_manifest(manifest):
    sha=manifest['upstream_sha']
    require(manifest.get('formal_validation')==context(sha) and
            manifest.get('patchset')=='v4' and
            manifest.get('custom_repository')==os.environ['GITHUB_REPOSITORY'] and
            manifest.get('custom_repository_sha')==os.environ['GITHUB_SHA'] and
            manifest.get('prepare_workflow_run')==os.environ['GITHUB_RUN_ID'] and
            manifest.get('client_update_identity',{}).get('channel')=='ci',
            'source manifest does not belong to this formal validation run')
    require(manifest.get('build_adapter_signature')==recipe_admission.source(sha)['build_signature'],
            'prepared build signature changed')
    return manifest['formal_validation']
