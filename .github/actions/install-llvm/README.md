# LLVM installer on Node.js 24

This is Kyle Mayes's Apache-2.0 licensed `install-llvm-action` v2.0.9,
commit `ebc0426251bc40c7cd31162802432c68818ab8f0`:
https://github.com/KyleMayes/install-llvm-action/tree/ebc0426251bc40c7cd31162802432c68818ab8f0

The upstream action still declares Node.js 20. The only local code/metadata change
is `action.yml` → `runs.using: node24`. The bundled JavaScript and asset catalog
are byte-for-byte upstream copies. `upstream.json` records their SHA-256 hashes
and the original metadata hash. Upstream source and dependency declarations remain
available at the immutable link above. `LICENSE.txt` retains the upstream license;
bundled dependency notices remain in `dist/main.js`.

Do not rebuild, edit the bundle, or change the asset catalog independently of an
explicit upstream refresh. Run `python3 -m scripts.validation.action_runtime_contract`
and the Windows `Action runtime compatibility` workflow after a refresh. The cached
entry-point check does not substitute for a real Windows download/extraction test.
When upstream releases a Node.js 24 action, evaluate replacing this local copy.
