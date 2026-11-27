#!/usr/bin/env bash
# Shared non-publishing fixture gate; sourced by existing platform build cores.
: "${PREPARED_SOURCE_DIR:?}" "${PLATFORM_ARCH:?}" "${VARIANT:?}" "${PLATFORM:?}"
[[ "${BUILD_CONFIGURATION:-}" == "TEST ONLY" &&
   "${BUILD_CHANNEL:-}" == ci && "${PATCHSET:-}" == v4 &&
   "${GITHUB_ACTIONS:-}" == true &&
   ( "${GITHUB_EVENT_NAME:-}" == pull_request || "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ) &&
   "${BUILD_FLAVOR:-}" == '' ]] || { echo 'BUILD_COMPAT: forbidden platform CI context' >&2; exit 1; }
[[ "$VARIANT" == standard || "$VARIANT" == sos ]] || exit 1
[[ "$PLATFORM" != android || "$VARIANT" == standard ]] || exit 1
source scripts/validation/test_config.sh
python3 - <<'PY'
import os,subprocess
from pathlib import Path
from scripts.platform.platform_adapter import check
from scripts.build.build_adapter import check as check_build
tree=Path(os.environ['PREPARED_SOURCE_DIR']).resolve()
assert tree==Path('.work/native/source').resolve(), 'CI source must be isolated'
assert os.environ['UPSTREAM_EXPECTED_SHA']=='51f94394ce61e1f3d26229565c326b2862cbdd1f'
assert subprocess.check_output(['git','-C',str(tree),'rev-parse','HEAD'],text=True).strip()==os.environ['UPSTREAM_EXPECTED_SHA']
for name in ('src/bridge_generated.rs','src/bridge_generated.io.rs'):
    assert (tree/name).is_file() and (tree/name).stat().st_size
p,_=check(tree,os.environ['PLATFORM'],os.environ['PLATFORM_ARCH'],channel='ci')
b=check_build(tree,channel='ci')
for value in (p,b):
    assert value.get('ci_candidate_only') is True and value.get('stable_allowed') is False
assert p['runner']==os.environ['EXPECTED_RUNNER']
if os.environ.get('FORMAL_VALIDATION')=='true':
    from scripts.build.formal_validation import worker_identity
    worker_identity(tree)
    assert p.get('production_recipe_approved') is True and p.get('release_eligible') is False
assert os.environ['RUSTDESK_ID_SERVER']=='test.invalid'
print('CI fixture source, platform and build signatures: PASS (not release approved)')
PY
