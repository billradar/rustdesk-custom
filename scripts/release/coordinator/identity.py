"""Versioned coordinator keys with byte-compatible historical digest adapters.

These keys are a new namespace, not permission to rebuild historical batches.
Callers must verify the existing channel evidence before reserving a new key.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re


def canonical(value):
    """The v1 encoding: sorted keys, compact UTF-8, no floats or NaN."""
    def check(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("Unsupported canonical JSON value")
    check(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def hex_value(value, length):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(length) + '}', value):
        raise ValueError("Invalid identity digest")


@dataclass(frozen=True)
class SourceIdentity:
    upstream_sha: str
    patchset: str
    common_patch_hash: str
    sos_patch_hash: str
    upstream_repository: str = 'rustdesk/rustdesk'

    def __post_init__(self):
        hex_value(self.upstream_sha, 40)
        hex_value(self.common_patch_hash, 64)
        hex_value(self.sos_patch_hash, 64)
        if (self.upstream_repository != 'rustdesk/rustdesk'
                or not re.fullmatch(r'v[1-9][0-9]*', self.patchset)):
            raise ValueError("Untrusted source or patchset")

    @property
    def key(self):
        return digest(dict(schema_version=1, kind='source', **asdict(self)))


@dataclass(frozen=True)
class BuildIdentity:
    channel: str
    source: SourceIdentity
    wayland_included: bool
    wayland_policy_sha256: str
    android_signing_enabled: bool
    release_mode: str = 'draft'
    policy_version: int = 1

    def __post_init__(self):
        if (self.channel not in ('stable', 'nightly')
                or not isinstance(self.source, SourceIdentity)
                or type(self.wayland_included) is not bool
                or type(self.android_signing_enabled) is not bool
                or type(self.policy_version) is not int or self.policy_version != 1
                or self.release_mode not in ('dry-run', 'draft', 'release')):
            raise ValueError("Unsupported build identity policy")
        if self.wayland_included:
            hex_value(self.wayland_policy_sha256, 64)
        elif self.wayland_policy_sha256 != '':
            raise ValueError("Disabled Wayland cannot have a policy digest")

    @property
    def key(self):
        # Stable publication mode is not part of its established build identity.
        data = asdict(self)
        if self.channel == 'stable':
            del data['release_mode']
        return digest(dict(schema_version=1, kind='build', **data))

    @property
    def historical_digest(self):
        """Reconstruct current Stable v4 / unversioned Nightly identity exactly."""
        data = asdict(self.source)
        del data['upstream_repository']
        if self.channel == 'stable':
            data.update(schema='stable-build-identity-v4',
                        wayland_included=self.wayland_included,
                        wayland_policy_sha256=self.wayland_policy_sha256,
                        android_signing_enabled=self.android_signing_enabled)
        else:
            data.update(wayland=str(self.wayland_included).lower(),
                        signing=str(self.android_signing_enabled).lower(),
                        wayland_policy_sha256=self.wayland_policy_sha256,
                        release_mode=self.release_mode)
        return digest(data)

    def verify_historical(self, value):
        # Equality alone is insufficient: existing lock/discovery/release gates
        # must validate provenance and evidence before calling this adapter.
        hex_value(value, 64)
        if value != self.historical_digest:
            raise ValueError("Historical identity requires review")
        return self.key


@dataclass(frozen=True)
class RunProvenance:
    custom_repository_sha: str
    workflow_run_id: str
    official_run_id: str = ''

    def __post_init__(self):
        hex_value(self.custom_repository_sha, 40)
        for value in (self.workflow_run_id, self.official_run_id):
            if value != '' and not re.fullmatch('[1-9][0-9]*', value):
                raise ValueError("Invalid run provenance")
        if not self.workflow_run_id:
            raise ValueError("Missing workflow run provenance")
