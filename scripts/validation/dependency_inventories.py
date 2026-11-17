"""Resolve checked-in Cargo fixture inventories without compiling inventory guards."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def validate():
    for name in ('diagnostic-logs', 'api-failover'):
        manifest = ROOT / 'scripts/validation/fixtures' / name / 'Cargo.toml'
        subprocess.run(['cargo', 'metadata', '--locked', '--format-version', '1',
                        '--manifest-path', str(manifest)], check=True,
                       stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    validate()
