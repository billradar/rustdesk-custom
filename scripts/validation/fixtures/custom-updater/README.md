These public metadata files came from Draft release 442501039, CD run
43146078797 at c1d6942ee173979a8d73c393a7ceb12abda20186. The original v1
manifest and Sigstore bundle exercise real cryptographic verification only.
The new updater intentionally rejects that historical schema.

`schema-v2-unsigned.json` is a constructed parser/selection fixture with all 31
installer selectors. Its synthetic Wayland policy hash is not release evidence.
It has no valid signature. Tests require that the historical proof fails for it.
A newly signed schema-v2 aggregate must still be validated in hosted CD before
publication; these fixtures do not claim a native build or device upgrade.

`cd-verified-claims.json` contains the maintained gh verifier's public certificate
and statement output for that same proof. Python tests exercise policy binding
on that output; they do not treat this JSON itself as a signed proof.
