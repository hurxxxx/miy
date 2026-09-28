from open_work_hub_api.core.app_registry import app_registration

TETRIS_APP = app_registration(
    "tetris", ai_capability_modules=("open_work_hub_api.domains.tetris.ai",)
)
