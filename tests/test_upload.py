import pytest

from clipper_flash.upload import UploadError, build_video_body


def test_body_basic() -> None:
    body = build_video_body("My clip", "desc here", "unlisted", ["#shorts"])
    assert body["snippet"]["title"] == "My clip"
    assert body["snippet"]["tags"] == ["#shorts"]
    assert body["status"]["privacyStatus"] == "unlisted"
    assert body["status"]["selfDeclaredMadeForKids"] is False


def test_title_truncated_to_100() -> None:
    body = build_video_body("x" * 250, "")
    assert len(body["snippet"]["title"]) == 100


def test_invalid_privacy_falls_back() -> None:
    body = build_video_body("t", "", "sneaky")
    assert body["status"]["privacyStatus"] == "private"


def test_empty_title_raises() -> None:
    with pytest.raises(UploadError):
        build_video_body("   ", "")


def test_kids_flag_passthrough() -> None:
    body = build_video_body("t", "", made_for_kids=True)
    assert body["status"]["selfDeclaredMadeForKids"] is True
