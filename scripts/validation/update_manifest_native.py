"""Run the actual patch-carried Sigstore verifier with its locked Rust dependencies."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from scripts.validation.client_update_contract import patch_file

ROOT=Path(__file__).resolve().parents[2]

def run(cargo='cargo'):
    with tempfile.TemporaryDirectory(prefix='rustdesk-update-verifier-') as td:
        tree=Path(td)
        for name in ('Cargo.toml','Cargo.lock','src/lib.rs'):
            p=tree/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(patch_file('v3','libs/custom_update_manifest/'+name))
        (tree/'tests').mkdir()
        (tree/'tests'/'integration.rs').write_bytes((ROOT/'scripts/validation/update_manifest_native_tests.rs').read_bytes())
        env=dict(os.environ,UPDATE_FIXTURES=str(ROOT/'scripts/validation/fixtures/custom-updater'))
        subprocess.run([cargo,'test','--locked','--manifest-path',str(tree/'Cargo.toml'),'--test','integration'],check=True,env=env)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cargo',default='cargo');args=p.parse_args();run(args.cargo)
