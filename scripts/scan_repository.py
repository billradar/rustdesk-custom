#!/usr/bin/env python3
"""Known CI credential patterns in committed maintenance files; no values printed."""
from pathlib import Path
import re
import subprocess
from production_config import TOKEN
ROOT=Path(__file__).resolve().parents[1]
BLOCK=re.compile(rb'-----BEGIN ([A-Z ]*PRIVATE KEY)-----[\s\S]+?-----END \1-----')

def scan():
    # Only tracked files; artifacts/workspaces are checked by their own gates.
    names=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z']).split(b'\0')
    for name in names:
        if not name:continue
        p=ROOT/name.decode();data=p.read_bytes()
        if TOKEN.search(data) or BLOCK.search(data):raise ValueError('Known credential in tracked repository file: '+name.decode()+' (value withheld)')
    print('Tracked repository known credential scan: PASS (headers alone in synthetic tests are not private-key blocks)')

if __name__=='__main__':scan()
