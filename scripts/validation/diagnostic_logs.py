"""Compile/test actual v3 diagnostic engine in isolation; never contacts production."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import re
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
FILES = ['flutter/lib/common/widgets/logs_page.dart', 'flutter/lib/common/diagnostic_events.dart', 'flutter/lib/common/diagnostic_rpc.dart']

def verify_inventory_manifest(inventory, actual):
    # Git's text attributes can produce CRLF in prepared Windows worktrees.
    # Normalize only those line endings; retain exact checks on all other bytes.
    if inventory.read_bytes().replace(b'\r\n', b'\n') != actual.read_bytes().replace(b'\r\n', b'\n'):
        raise ValueError('Diagnostic dependency inventory differs from actual source')

def source_contract(source):
    source=Path(source)
    inventory=ROOT/'scripts/validation/fixtures/diagnostic-logs/Cargo.toml'
    verify_inventory_manifest(inventory, source/'libs/radar_diagnostics/Cargo.toml')
    for name in ["Cargo.toml","Cargo.lock","libs/hbb_common/Cargo.toml","libs/radar_diagnostics/Cargo.toml"]:
        tomllib.loads((source/name).read_text())
    for name in FILES + ['libs/radar_diagnostics/src/lib.rs','libs/radar_diagnostics/Cargo.toml']:
        if not (source/name).is_file():
            raise ValueError('Missing unified diagnostic source: '+name)
    bridge=(source/'src/flutter_ffi.rs').read_text()
    if 'pub fn main_diagnostics' in bridge or 'radar-diagnostic-request:' not in bridge or 'radar-diagnostic-result:' not in bridge:
        raise ValueError('Diagnostic transport must preserve the original bridge ABI')
    common=(source/'libs/hbb_common/src/lib.rs').read_text()
    android=(source/'src/platform/android_log.rs').read_text()
    for value in (bridge,common,android):
        if re.search(r'radar_diagnostics::initialize\(\s*(?:config::)?Config::log_path',value):
            raise ValueError('Diagnostics initialized before private storage resolution')
    if 'hbb_common::diagnostics_path()' not in bridge:
        raise ValueError('First initialization must use the private storage resolver')
    for value in (common,android):
        if 'radar_diagnostics' not in value or '.format(opt_format)' in value:
            raise ValueError('Unmanaged legacy file formatter')
    if 'record.args()' in (source/'libs/radar_diagnostics/src/lib.rs').read_text().replace('//! Optional local diagnostics. Arbitrary log arguments NEVER enter this store.',''):
        raise ValueError('Raw log arguments imported')
    for path in (source/'flutter/android/app/src/main/kotlin').rglob('*.kt'):
        if path.name!='DiagnosticLog.kt' and (('import android.util.Log' in path.read_text() and re.search(r'\bLog\.',path.read_text())) or 'android.util.Log.' in path.read_text() or '.printStackTrace()' in path.read_text()):
            raise ValueError('Unmanaged native log: '+str(path.relative_to(source)))
    keyboard=source/'flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/KeyboardKeyEventMapper.kt'
    if re.search(r'(?:Log|DiagnosticLog)\.d\(',keyboard.read_text()):
        raise ValueError('Per-key input events must never be logged')
    return {'adapter_source_contract':'PASS'}

def adapter_regressions(source):
    from unittest.mock import patch
    source=Path(source)
    original=Path.read_text
    bridge=source/'src/flutter_ffi.rs'
    actual=original(bridge)
    insecure=actual.replace('radar_diagnostics::initialize(path)', 'radar_diagnostics::initialize(config::Config::log_path().join("diagnostics"))',1)
    if insecure==actual:
        raise ValueError('Private initializer regression target missing')
    for modified in [insecure,actual+'\npub fn main_diagnostics(request: String) -> String { request }\n']:
        def read(path,*args,**kwargs):
            return modified if path==bridge else original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):
            try:
                source_contract(source)
            except ValueError:
                continue
            raise ValueError('Unsafe adapter regression was not rejected')
    manifest=(source/'libs/radar_diagnostics/Cargo.toml').read_bytes().replace(b'\r\n',b'\n')
    with tempfile.TemporaryDirectory(prefix='diagnostic-manifest-regression-') as directory:
        inventory=Path(directory)/'inventory.toml'
        actual=Path(directory)/'actual.toml'
        inventory.write_bytes(manifest)
        actual.write_bytes(manifest.replace(b'\n',b'\r\n'))
        verify_inventory_manifest(inventory,actual)
        verify_inventory_manifest(actual,inventory)
        for changed in [
            manifest.replace(b'serde = { version = "1"', b'serde = { version = "2"',1),
            manifest.replace(b'features = ["derive"]', b'features = []',1),
            manifest+b'\n[target.\'cfg(windows)\'.dependencies]\nwindows-sys = "0.52"\n',
        ]:
            if changed==manifest:
                raise ValueError('Manifest regression mutation missing')
            actual.write_bytes(changed.replace(b'\n',b'\r\n'))
            try:
                verify_inventory_manifest(inventory,actual)
            except ValueError:
                continue
            raise ValueError('Dependency drift accepted after newline normalization')
    return {'adapter_negative_regressions':'PASS','manifest_newline_and_dependency_regressions':'PASS'}

def run(source,output,targets=()):
    source=Path(source)
    result={'overall':'FAIL'}
    try:
        result.update(source_contract(source))
        result.update(adapter_regressions(source))
        with tempfile.TemporaryDirectory(prefix='radar-diagnostics-') as directory:
            tree=Path(directory)
            shutil.copytree(source/'libs/radar_diagnostics/src',tree/'src')
            shutil.copyfile(source/'libs/radar_diagnostics/Cargo.toml',tree/'Cargo.toml')
            shutil.copyfile(ROOT/'scripts/validation/fixtures/diagnostic-logs/Cargo.lock',tree/'Cargo.lock')
            env=dict(os.environ,CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR',str(ROOT/'.work/diagnostic-target')))
            # Process-spawning cases must not inherit unrelated cases' live OS locks.
            # Each concurrency case still runs its explicit threads/processes in parallel.
            for name,args in [('format',['fmt','--check']),('runtime_tests',['test','--locked','--','--test-threads=1']),('clippy',['clippy','--locked','--all-targets','--','-D','warnings'])]:
                result[name]='FAIL'
                subprocess.run(['cargo',*args],cwd=tree,env=env,check=True)
                result[name]='PASS'
            for target in targets:
                subprocess.run(['cargo','check','--locked','--lib','--target',target],cwd=tree,env=env,check=True)
                result['core_compile_'+target]='PASS'
        result['source_sha256']=hashlib.sha256((source/'libs/radar_diagnostics/src/lib.rs').read_bytes()).hexdigest()
        result['compiler']=subprocess.check_output(['rustc','--version'],text=True).strip()
        result['full_client_build']='NOT RUN'
        result['device_runtime']='NOT RUN'
        result['overall']='PASS'
    finally:
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        Path(output).write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--targets',nargs='*',default=[],choices=['aarch64-linux-android','armv7-linux-androideabi','x86_64-linux-android'])
    args=parser.parse_args()
    run(args.source,args.output,args.targets)
