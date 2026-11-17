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

def source_contract(source):
    source=Path(source)
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
    for value in (common,android):
        if 'radar_diagnostics' not in value or '.format(opt_format)' in value:
            raise ValueError('Unmanaged legacy file formatter')
    if 'record.args()' in (source/'libs/radar_diagnostics/src/lib.rs').read_text().replace('//! Optional local diagnostics. Arbitrary log arguments NEVER enter this store.',''):
        raise ValueError('Raw log arguments imported')
    for path in (source/'flutter/android/app/src/main/kotlin').rglob('*.kt'):
        if path.name!='DiagnosticLog.kt' and (('import android.util.Log' in path.read_text() and re.search(r'\bLog\.',path.read_text())) or 'android.util.Log.' in path.read_text() or '.printStackTrace()' in path.read_text()):
            raise ValueError('Unmanaged native log: '+str(path.relative_to(source)))
    return {'adapter_source_contract':'PASS'}

def run(source,output,targets=()):
    source=Path(source)
    result={'overall':'FAIL'}
    try:
        result.update(source_contract(source))
        with tempfile.TemporaryDirectory(prefix='radar-diagnostics-') as directory:
            tree=Path(directory)
            shutil.copytree(source/'libs/radar_diagnostics/src',tree/'src')
            shutil.copyfile(source/'libs/radar_diagnostics/Cargo.toml',tree/'Cargo.toml')
            shutil.copyfile(ROOT/'scripts/validation/fixtures/diagnostic-logs/Cargo.lock',tree/'Cargo.lock')
            env=dict(os.environ,CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR',str(ROOT/'.work/diagnostic-target')))
            for name,args in [('format',['fmt','--check']),('runtime_tests',['test','--locked']),('clippy',['clippy','--locked','--all-targets','--','-D','warnings'])]:
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
