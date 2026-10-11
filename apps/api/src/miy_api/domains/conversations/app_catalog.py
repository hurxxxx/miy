from miy_api.core.app_registry import app_registration

CHATBOT_APP = app_registration("chatbot", ai_capability_modules=('miy_api.domains.ai',))
