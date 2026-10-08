"""Platform-only contract artifact; business traffic remains inactive until cutover."""

from miy_api.app import create_app

app = create_app(composition="platform", initialize_runtime=False)
