from miy_api.core.app_registry import (
    AppNavRegistration,
    app_registration,
)

BENTO_APP = app_registration(
    "bento",
    ai_capability_modules=('miy_api.domains.bento',),
    nav_items=(
        AppNavRegistration(
            id="bento-all",
            title="All Presentations",
            category="Library",
            icon_key="presentation",
        ),
        AppNavRegistration(
            id="bento-mine",
            title="My Presentations",
            category="Library",
            icon_key="user",
        ),
        AppNavRegistration(
            id="bento-archived",
            title="Archived",
            category="Library",
            icon_key="history",
        ),
    ),
)
