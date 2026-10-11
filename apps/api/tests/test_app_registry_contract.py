from __future__ import annotations

import pytest

from miy_api.core.app_registry import (
    AppNavRegistration,
    AppRegistration,
    compile_app_registry,
)


def _registration(
    app_id: str,
    *,
    nav_items: tuple[AppNavRegistration, ...] = (),
) -> AppRegistration:
    return AppRegistration(
        app_id=app_id,
        title=app_id,
        route_base=f"/apps/{app_id}",
        icon_key="box",
        launcher_category=True,
        nav_items=nav_items,
    )


def test_production_registry_rejects_identity_drift_from_generated_contract() -> None:
    with pytest.raises(
        RuntimeError,
        match="App registration disagrees with generated contract for docs",
    ):
        compile_app_registry(
            (
                AppRegistration(
                    app_id="docs",
                    title="Docs",
                    route_base="/apps/wrong-docs",
                    icon_key="files",
                ),
            ),
            require_generated_contract=True,
        )
