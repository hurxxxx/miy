from mty_api.core.app_registry import app_registration

CHATBOT_APP = app_registration("chatbot", ai_capability_modules=('mty_api.domains.ai',))
