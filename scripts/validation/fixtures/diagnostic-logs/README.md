# Diagnostic dependency inventory

This Cargo manifest mirrors the actual `libs/radar_diagnostics/Cargo.toml` rendered
by v3. It exists so dependency graph/security update tooling can resolve the
checked-in lockfile without requiring generated prepared source.

`src/lib.rs` deliberately fails compilation: it is an inventory, not a second
logging implementation. `diagnostic_logs.py` compares this manifest byte-for-byte after CRLF-to-LF normalization only
with prepared source and then compiles/tests the actual prepared-source crate.
The API fixture's facade points here for static analysis; its runtime harness
rebinds that one path to the actual prepared source copied into its private temp
project. It never builds this guard as a substitute.

`dependency_inventories.py` resolves both checked-in fixtures with locked Cargo
metadata in PR CI. Do not remove dependencies, suppress security scanning or use
inventory updates alone as evidence that production dependencies were updated.
