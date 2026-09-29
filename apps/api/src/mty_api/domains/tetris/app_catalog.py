from mty_api.core.app_registry import app_registration

TETRIS_APP = app_registration(
    "tetris", ai_capability_modules=("mty_api.domains.tetris.ai",)
)
