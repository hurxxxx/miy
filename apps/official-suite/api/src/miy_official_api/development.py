"""Development API entry; the dedicated Vite process owns the official UI."""

from miy_api.app import create_first_party_app

app = create_first_party_app(composition="official")
