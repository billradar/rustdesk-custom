"""Only the exact reviewed local dependency may be hidden from upstream recipe hashes."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.build.updater_dependencies import CARGO_BLOCK,cargo_for_adapter

class DependencyTests(unittest.TestCase):
    def test_exact_addition_and_every_other_manifest_change(self):
        with tempfile.TemporaryDirectory() as td:
            tree=Path(td);p=tree/'Cargo.toml';original='[package]\nname="fixture"\n[dependencies]\nserde="1"\n'
            p.write_text(original)
            subprocess.run(['git','init','-q',td],check=True)
            subprocess.run(['git','-C',td,'add','Cargo.toml'],check=True)
            subprocess.run(['git','-C',td,'-c','user.name=Contract','-c','user.email=contract@example.invalid','-c','commit.gpgsign=false','commit','-qm','upstream'],check=True)
            self.assertEqual(cargo_for_adapter(tree),original.encode())
            exact=original.replace('[dependencies]\n','[dependencies]\n'+CARGO_BLOCK)
            p.write_text(exact);self.assertEqual(cargo_for_adapter(tree),original.encode())
            p.write_bytes(exact.replace('\n','\r\n').encode());self.assertEqual(cargo_for_adapter(tree),original.encode())
            for changed in (exact.replace('serde="1"','serde="2"'),exact.replace('libs/custom_update_manifest','other/path'),exact+CARGO_BLOCK,exact.replace('name="fixture"','name="different"')):
                p.write_text(changed)
                with self.assertRaises(ValueError):cargo_for_adapter(tree)

if __name__=='__main__':unittest.main()
