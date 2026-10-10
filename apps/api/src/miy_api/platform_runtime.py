"""Explicit platform process; legacy writer/authority remain a shared boundary."""

from miy_api.app import create_first_party_app

app = create_first_party_app(composition="platform")
