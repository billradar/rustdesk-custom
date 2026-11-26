"""Explicit credential-free formal validation context; never authorizes releases."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from scripts.build import recipe_admission

def require(ok,message):
    if not ok:
        raise ValueError('FORMAL_VALIDATION: '+message)

def context(sha):
    require(os.environ.get('GITHUB_ACTIONS')=='true' and
            os.environ.get('GITHUB_REPOSITORY')=='billradar/rustdesk-custom' and
            os.environ.get('GITHUB_EVENT_NAME') in ('pull_request','workflow_dispatch') and
            os.environ.get('BUILD_CHANNEL')=='ci' and
            (os.environ.get('BUILD_CONFIGURATION')=='TEST ONLY' or
             (os.environ.get('BUILD_CONFIGURATION')=='CI_PACKAGE_TEST' and
              os.environ.get('FORMAL_VALIDATION')=='true' and os.environ.get('PLATFORM')=='linux')) and
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

def worker_identity(tree, variant=None):
    """Full inventory is verified during unpack; bind later build/report checks to that source manifest."""
    tree=Path(tree).resolve()
    require(os.environ.get('FORMAL_VALIDATION')=='true' and
            tree==Path('.work/native/source').resolve(),
            'explicit isolated formal worker required')
    path=tree/'source-manifest.json'
    require(path.is_file() and not path.is_symlink(),'formal source manifest required')
    manifest=json.loads(path.read_bytes())
    marker=verify_manifest(manifest)
    variant=variant or os.environ.get('VARIANT')
    require(variant in ('standard','sos') and manifest.get('variant')==variant and
            subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD'],text=True).strip()==marker['upstream_sha'],
            'formal worker source or variant mismatch')
    from scripts.upstream.patchsets import patch_hash
    require(manifest.get('common_patch_hash')==patch_hash('common','v4') and
            manifest.get('sos_patch_hash')==(patch_hash('sos','v4') if variant=='sos' else None),
            'formal worker patch content mismatch')
    return dict(formal_validation=marker,
                source_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                variant=variant,release_eligible=False)
