from __future__ import annotations


from miy_api.domains.auth.roles import (
    SYSTEM_PLATFORM_ADMIN,
    normalize_system_role,
)


def test_only_canonical_platform_role_grants_authority() -> None:
    assert normalize_system_role("platform_admin") == SYSTEM_PLATFORM_ADMIN
    assert normalize_system_role("platform-admin") is None
