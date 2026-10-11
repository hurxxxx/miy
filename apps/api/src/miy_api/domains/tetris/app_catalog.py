from miy_api.core.app_registry import app_registration

TETRIS_APP = app_registration(
    "tetris", ai_capability_modules=("miy_api.domains.tetris.ai",)
)
