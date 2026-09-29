from mty_api.mty_desktop_update_serving_policy import (
    mty_desktop_update_serving_policy,
)


def test_mty_desktop_update_serving_policy_uses_manifest_contract() -> None:
    policy = mty_desktop_update_serving_policy()

    assert policy.platforms == ("win", "mac", "linux")
    assert policy.feed_path_prefix == "/api/v1/mty-desktop/updates"
    assert policy.is_allowed_file_path("mac", "latest-mac.yml")
    assert not policy.is_allowed_file_path("mac", "latest.yml")
    assert policy.is_allowed_file_path("linux", "MTY-Desktop-latest.deb.blockmap")
    assert not policy.is_allowed_file_path("linux", "MTY-Desktop-latest.exe")


def test_mty_desktop_update_serving_policy_attachment_headers() -> None:
    policy = mty_desktop_update_serving_policy()

    headers = policy.attachment_headers("linux", "MTY-Desktop-latest.deb")

    assert headers is not None
    assert headers.content_type == "application/vnd.debian.binary-package"
    assert headers.content_disposition.startswith("attachment;")
    assert "MTY-Desktop-latest.deb" in headers.content_disposition
    assert policy.attachment_headers("linux", "MTY-Desktop-latest.deb.blockmap") is None
    assert policy.attachment_headers("linux", "nested/MTY-Desktop-latest.deb") is None


def test_mty_desktop_update_serving_policy_rejects_unsafe_public_paths() -> None:
    policy = mty_desktop_update_serving_policy()

    assert not policy.is_allowed_file_path("win", "")
    assert not policy.is_allowed_file_path("win", ".hidden.exe")
    assert not policy.is_allowed_file_path("win", "nested/MTY-Desktop-Setup-latest.exe")
    assert not policy.is_allowed_file_path("win", "MTY-Desktop-Setup-latest.exe\n")
    assert not policy.is_allowed_file_path("unknown", "MTY-Desktop-Setup-latest.exe")
