from miy_api.miy_desktop_update_serving_policy import (
    miy_desktop_update_serving_policy,
)


def test_miy_desktop_update_serving_policy_uses_manifest_contract() -> None:
    policy = miy_desktop_update_serving_policy()

    assert policy.platforms == ("win", "mac", "linux")
    assert policy.feed_path_prefix == "/api/v1/miy-desktop/updates"
    assert policy.is_allowed_file_path("mac", "latest-mac.yml")
    assert not policy.is_allowed_file_path("mac", "latest.yml")
    assert policy.is_allowed_file_path("linux", "MIY-Desktop-latest.deb.blockmap")
    assert not policy.is_allowed_file_path("linux", "MIY-Desktop-latest.exe")


def test_miy_desktop_update_serving_policy_attachment_headers() -> None:
    policy = miy_desktop_update_serving_policy()

    headers = policy.attachment_headers("linux", "MIY-Desktop-latest.deb")

    assert headers is not None
    assert headers.content_type == "application/vnd.debian.binary-package"
    assert headers.content_disposition.startswith("attachment;")
    assert "MIY-Desktop-latest.deb" in headers.content_disposition
    assert policy.attachment_headers("linux", "MIY-Desktop-latest.deb.blockmap") is None
    assert policy.attachment_headers("linux", "nested/MIY-Desktop-latest.deb") is None


def test_miy_desktop_update_serving_policy_rejects_unsafe_public_paths() -> None:
    policy = miy_desktop_update_serving_policy()

    assert not policy.is_allowed_file_path("win", "")
    assert not policy.is_allowed_file_path("win", ".hidden.exe")
    assert not policy.is_allowed_file_path("win", "nested/MIY-Desktop-Setup-latest.exe")
    assert not policy.is_allowed_file_path("win", "MIY-Desktop-Setup-latest.exe\n")
    assert not policy.is_allowed_file_path("unknown", "MIY-Desktop-Setup-latest.exe")
