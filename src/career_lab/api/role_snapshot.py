"""Compatibility exports for the fixed-job role snapshot adapter."""

from career_lab.runtime import role_snapshot as _snapshot

FixedRoleSnapshotPort = _snapshot.FixedRoleSnapshotPort
_before = _snapshot._before
activated_catalog = _snapshot.activated_catalog
activated_reference = _snapshot.activated_reference
