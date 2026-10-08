"""ASGI artifact with owned routes/schema, health, and a closed activation boundary."""
from miy_api.app import create_app

app = create_app(composition="official", initialize_runtime=False)
