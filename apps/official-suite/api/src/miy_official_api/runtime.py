"""Official business process using current first-party authority and storage."""

from miy_api.app import create_first_party_app

from miy_official_api.frontend import mount_official_frontend, read_platform_build_id

frontend_dir = "dist/apps/official-suite"
platform_build_id = read_platform_build_id(frontend_dir)
app = create_first_party_app(composition="official", client_build_id=platform_build_id)
# The independent service artifact always includes its matching reviewed UI build.
mount_official_frontend(app, frontend_dir, platform_build_id=platform_build_id)
