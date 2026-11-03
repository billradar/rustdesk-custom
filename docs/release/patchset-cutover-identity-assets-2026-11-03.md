# Cutover identity mapping and release asset audit — 2026-11-03

**Scope:** read-only repository and GitHub REST evidence. **Decision: BLOCKED.** No historical ref, release, tag, signing material or cutover state was changed.

## Legacy → content identity

The immutable catalog at `metadata/release/coordinator-legacy/objects/d662ffb7f8c1c9d6fdd72000660c2bdb9c5772664e453e967c7290f6897c7da1.json` contains 25 reviewed historical records:

- 7 `VERIFIED_LEGACY_SUCCESS_IDENTITY`
- 15 `REVIEW_REQUIRED`
- 2 `NO_BUILD_IDENTITY_REVIEW`
- 1 `NO_BUILD_REUSE` (not an eligible producer-success alias)

The seven verified producer mappings are:

| Historical Run | Legacy v1 digest | Content identity |
| --- | --- | --- |
| 40550247760 | `9ebfed67f66a6af9d65466c6c56df8bffa6287609c1575d8557e608c2a33d759` | `8e2e810e81efe05eca07d9e8690027f131e7d42b845507f2ebcb955e9d29b50d` |
| 40737839195 | `665b101b2d2d1a752c64e113af7fbc0389d39647727b5a55d60a42f38c97587a` | `a7713138a844cff168e569c769c988e7bef811521404e3a1691c5a01c5159a86` |
| 40924598685 | `7f2a9512f31cf91c627e4488889c03a8ca9fde941b7efb608c32e4c05c153541` | `e44966ae7135b77c5f94a08fa6489ed4fb1514d67deb3c13114a64147425176b` |
| 41292973439 | `43689e62d6b58d651678dc62b450c61b6bf7d8141256f54b700b124b95bb42cd` | `7fa822c3f1a3291dce82f69bd3875484d797c48a5c970136b0126c141a02545c` |
| 41422335564 | `a3b5d1145d568983717400958c43a3178d1e56e551a4e3a6493fa11e7e91adad` | `c46008d9ac6d7e56accc4c1e295e841efd2cf8c1db69b12b085dfe779164cf1b` |
| 41289240322 | `d9cb2c710b9efbd9f127fca98da58431597c1c92f4c2ac340edb76bc24a65bff` | `983122dbf9b512a378956e6d1f03bb6d8242787656409e9787377a5faad72f08` |
| 41398573672 | `0d5dd098c5ce4211570ace802496f331fa90fd431969b692b0aa21e9a5b9859e` | `e3fc1025a3af8830537446ecf5aa5218e42185de65d10a1b1dbd38f275233d48` |

The `v1.5.1-custom.v2.1` draft's historical metadata `build_identity` equals the **legacy** digest for run 41398573672, not its content identity. Therefore a migration must recognize both representations without treating them as independent publishable builds. The catalog's `legacy.py` validation prohibits positive aliases for review-required identities and enforces archived source provenance.

This is an evidence-backed candidate mapping inventory, **not** a proven collision-free production migration. Runtime deduplication, source scope conflicts and no-build exclusions require executable gate tests before activation.

## GitHub draft release assets

At the time of inspection, three draft releases each expose 32 assets (96 total asset records). Each asset has a GitHub REST SHA-256 digest and a size. Git tag target SHA matches release target SHA for all three when compared by intended release name, but stable drafts use GitHub `untagged-*` API tag names rather than the existing named tags.

| Draft release ID | Display name | Git tag | Target SHA | Assets |
| --- | --- | --- | --- | --- |
| 432254527 | nightly | nightly | `8d6f0b96aba2d20255381585f2bd3ecb82aa356a` | 32 |
| 431170313 | v1.5.1-custom.v2.1 | v1.5.1-custom.v2.1 | `82859cd32d4608e6507314de1cdd5cf9ebb2860c` | 32 |
| 430489827 | v1.5.0-custom.v2.6 | v1.5.0-custom.v2.6 | `bed8113783f8e9da9ae0ae9a4b300f68bc445ddd` | 32 |

The current nightly draft has three named signed Android APKs, while macOS DMGs are explicitly named unsigned. The inventory contains Windows Standard/SOS, Linux Standard/SOS, experimental Wayland DEBs and SHA256SUMS.

**Limitations:** Asset digests were observed in GitHub REST metadata but asset bytes were not downloaded/rehashed. SHA256SUMS contents were not independently cross-checked. Android APK v2/v3 signatures, signer certificate identity, Windows/macOS signatures, provenance attestations and external distribution channels were not independently verified. Equal asset counts do not establish complete provenance or absence of duplicates.

## Unresolved risks and acceptance gates

1. Keep deleted historical Actions run 41549385808 at `REVIEW_REQUIRED` until a permitted evidence-based disposition exists.
2. Exercise legacy alias collision, `NO_BUILD_REUSE`, unknown identity and stable/nightly publish-dedup contracts on current main.
3. Download and rehash all 96 assets; compare SHA256SUMS, inspect APK signer certificates and signed package attestations where applicable. Explicitly distinguish unsigned artifacts.
4. Verify no duplicate publication by comparing release IDs, historical identity metadata, tag target SHAs and all distribution destinations.
5. Run up-to-date Patchset Version and coordinator gates on current main. The existing `docs/audits/patchset-version-20261103/validation.json` records 492 historical Python tests passing at baseline `2b871ad...`, **not** an up-to-date current-main gate.
6. Leave `metadata/release/patchset-cutover.json` at `BLOCKED` until a separate reviewed migration meets all prerequisites.

No cutover activation or production signing was performed in this audit.
