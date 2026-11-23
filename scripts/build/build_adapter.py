#!/usr/bin/env python3
"""Reviewed exact-source build profiles. Unknown critical definitions fail closed."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[2]
CRITICAL_FILES = ['build.py', 'build.rs', '.github/workflows/bridge.yml',
                  '.github/workflows/third-party-RustDeskTempTopMostWindow.yml',
                  '.github/patches/flutter_3.24.4_dropdown_menu_enableFilter.diff']
TOOLS = ['RUST_VERSION', 'FLUTTER_VERSION', 'LLVM_VERSION', 'VCPKG_COMMIT_ID']

def _digest_value(value):
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            # PyYAML's YAML 1.1 resolver turns keys such as "on"/"off"
            # into bools. Normalize mapping keys before JSON sorting.
            normalized_key = key if isinstance(key, str) else str(key)
            if normalized_key in normalized:
                raise ValueError('Digest mapping key collision after key normalization')
            normalized[normalized_key] = _digest_value(item)
        return normalized
    if isinstance(value, list):
        return [_digest_value(item) for item in value]
    if isinstance(value, tuple):
        return [_digest_value(item) for item in value]
    return value


def digest(data):
    canonical = _digest_value(data)
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def inspect(tree):
    tree=Path(tree)
    build=yaml.safe_load((tree/'.github/workflows/flutter-build.yml').read_text())
    env=build['env']; job=build['jobs']['build-for-windows-flutter']
    rows=job['strategy']['matrix']['job']
    x64=next(r for r in rows if r['target']=='x86_64-pc-windows-msvc')
    runner=x64.get('os', x64.get('runner'))
    # The official matrix calls its runner field "os" or "on" across snapshots.
    runner=runner or x64.get('on') or x64.get(True)
    if runner!='windows-2022': raise ValueError('Unsupported official Windows x64 runner')
    critical={'windows_job':job,'tools':{k:env[k] for k in TOOLS},'files':{}}
    for p in CRITICAL_FILES:
        critical['files'][p]=hashlib.sha256((tree/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    version=re.search(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+(?:[-+][\w.-]+)?)"',
                      (tree/'Cargo.toml').read_text(),re.M)
    if not version: raise ValueError('Upstream source version missing')
    bridge=yaml.safe_load((tree/'.github/workflows/bridge.yml').read_text())
    b_env=bridge['env']
    bridge_profile=next(r for r in bridge['jobs']['generate_bridge']['strategy']['matrix']['job'] if r['artifact-name']=='bridge-artifact')
    helper=re.search(r'git checkout\s+([0-9a-f]{40})',(tree/'.github/workflows/third-party-RustDeskTempTopMostWindow.yml').read_text())
    if not helper: raise ValueError('Official helper pin missing')
    profile={'signature':digest(critical),'upstream_version':version.group(1),
             'runner':runner,'rust':str(env['RUST_VERSION']), 'flutter':str(env['FLUTTER_VERSION']),
             'llvm':str(env['LLVM_VERSION']), 'vcpkg':env['VCPKG_COMMIT_ID'],
             'bridge_rust':str(b_env['RUST_VERSION']), 'cargo_expand':str(b_env['CARGO_EXPAND_VERSION']),
             'frb':str(b_env['FLUTTER_RUST_BRIDGE_VERSION']), 'bridge_flutter':str(bridge_profile['flutter-version']),
             'helper_commit':helper.group(1),
             'source_sbom_requested':'generate-sbom' in build['jobs']}
    return profile, critical

def _official_sha(tree):
    """Use the actual checked-out source commit, never a claimed branch/version."""
    sha=subprocess.check_output(
        ['git','-C',str(Path(tree)),'rev-parse','HEAD'],text=True).strip()
    if not re.fullmatch(r'[0-9a-f]{40}',sha):
        raise ValueError('BUILD_COMPATIBILITY=FAIL: invalid official source SHA')
    return sha


def _ci_candidate(tree, profile):
    registry=json.loads((ROOT/'metadata/build/adapter-ci-candidates.json').read_text())
    if registry.get('schema')!='build-adapter-ci-candidates-v1':
        raise ValueError('BUILD_COMPATIBILITY=FAIL: invalid candidate manifest schema')
    source_sha=_official_sha(tree)
    for row in registry.get('candidates',[]):
        if row.get('source_sha')!=source_sha:
            continue
        if (row.get('ci_only') is not True or row.get('stable_allowed') is not False
                or row.get('upstream_version')!=profile['upstream_version']
                or row.get('signature')!=profile['signature']
                or not re.fullmatch(r'[0-9a-f]{64}',row.get('signature',''))
                or not re.fullmatch(r'[a-zA-Z0-9-]+',row.get('id',''))):
            raise ValueError('BUILD_COMPATIBILITY=FAIL: source-specific CI candidate drift')
        return row
    raise ValueError('BUILD_COMPATIBILITY=FAIL: unknown critical official Windows/bridge/build interface; review in staging')


def check(tree,channel='stable'):
    """Only explicit CI may validate a candidate; Stable remains fail-closed."""
    if channel not in ('ci','stable'):
        raise ValueError('BUILD_COMPATIBILITY=FAIL: invalid adapter channel')
    profile,critical=inspect(tree)
    known=json.loads((ROOT/'metadata/build/adapter-profiles.json').read_text())
    approved=next((p for p in known['profiles'] if p['signature']==profile['signature']),None)
    if approved is None:
        if channel!='ci':
            raise ValueError('BUILD_COMPATIBILITY=FAIL: unknown critical official Windows/bridge/build interface; review in staging')
        candidate=_ci_candidate(tree,profile)
        profile.update(reviewed_profile=candidate['id'],ci_candidate_only=True,
                       stable_allowed=False,candidate_source_sha=candidate['source_sha'],
                       adapter_review_status='CI_CANDIDATE_NOT_RELEASE_APPROVED')
    else:
        profile['reviewed_profile']=approved['id']
        profile['ci_candidate_only']=False
    profile['Build Compatibility']='PASS'
    return profile

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('tree',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--channel',choices=('ci','stable'),default='stable')
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        result=check(args.tree,channel=args.channel)
    except Exception as e:
        failure={'Build Compatibility':'FAIL','reason':str(e)}
        # Keep a machine-readable review packet for unknown upstream signatures. This is diagnostic
        # evidence only: it does not approve the profile or relax the fail-closed gate.
        try:
            observed, critical=inspect(args.tree)
            failure['observed_profile']=observed
            failure['critical']=critical
        except Exception as diagnostic_error:
            failure['diagnostic_error']=str(diagnostic_error)
        args.output.write_text(json.dumps(failure,indent=2)+'\n')
        raise
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:
            for k,v in result.items():
                if isinstance(v,(str,int,bool)) and re.fullmatch(r'[A-Za-z_]+',k): f.write(f'{k}={str(v).lower() if isinstance(v,bool) else v}\n')
