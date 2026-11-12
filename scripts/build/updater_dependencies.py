"""Canonicalize only the exact reviewed updater dependency addition for adapters."""
from pathlib import Path
import subprocess

CARGO_BLOCK = ('# BEGIN reviewed custom update verifier\n'
               'rustdesk-update-manifest = { path = "libs/custom_update_manifest" }\n'
               '# END reviewed custom update verifier\n')


def cargo_for_adapter(tree):
    tree=Path(tree)
    raw=(tree/'Cargo.toml').read_bytes().replace(b'\r\n',b'\n')
    marker=b'# BEGIN reviewed custom update verifier'
    if marker not in raw:
        return raw
    if raw.count(CARGO_BLOCK.encode())!=1 or raw.count(marker)!=1:
        raise ValueError('Unreviewed updater dependency block')
    original=subprocess.check_output(['git','-C',str(tree),'show','HEAD:Cargo.toml']).replace(b'\r\n',b'\n')
    if original.count(b'[dependencies]\n')!=1:
        raise ValueError('Unexpected upstream Cargo dependency layout')
    expected=original.replace(b'[dependencies]\n',b'[dependencies]\n'+CARGO_BLOCK.encode(),1)
    if raw!=expected:
        raise ValueError('Cargo manifest contains changes outside the reviewed updater dependency')
    return original
