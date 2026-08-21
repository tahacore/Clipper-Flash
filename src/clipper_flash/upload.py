"""YouTube upload via the official Data API (user's own OAuth project).

Setup (one-time, documented in README):
1. Create a Google Cloud project, enable YouTube Data API v3.
2. Create an OAuth *Desktop* client id, download client_secret.json.
3. First `cf upload` run opens a browser for consent; token is cached.

Note: until Google audits your API project, uploads may be locked to private
by YouTube API policy - this is a platform rule, not a bug. Use --privacy
to control what you request.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_PATH = Path.home() / ".clipper-flash" / "oauth_token.json"


class UploadError(RuntimeError):
    pass


@dataclass
class UploadResult:
    video_id: str
    url: str
    privacy: str


def build_video_body(
    title: str,
    description: str,
    privacy: str = "unlisted",
    tags: list[str] | None = None,
    made_for_kids: bool = False,
) -> dict:
    """Pure helper (unit-testable): API request body for videos.insert."""
    if not title.strip():
        raise UploadError("title must not be empty")
    return {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or [],
            "categoryId": "24",  # Entertainment; agents may override per content
        },
        "status": {
            "privacyStatus": privacy if privacy in ("public", "unlisted", "private") else "private",
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }


def get_authenticated_service(client_secret: str | Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise UploadError(
            "upload extras missing - install with: uv tool install 'clipper-flash[upload]'"
        ) from exc

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret_path = Path(client_secret)
            if not secret_path.exists():
                raise UploadError(
                    f"client secret not found: {secret_path} - see README 'Auto-upload' setup"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds)


def upload_video(
    file_path: str | Path,
    title: str,
    description: str = "",
    privacy: str = "unlisted",
    tags: list[str] | None = None,
    client_secret: str | Path = "client_secret.json",
) -> UploadResult:
    """Upload one finished clip. Returns the watch URL."""
    from googleapiclient.http import MediaFileUpload

    path = Path(file_path)
    if not path.exists():
        raise UploadError(f"file not found: {path}")
    body = build_video_body(title, description, privacy, tags)

    youtube = get_authenticated_service(client_secret)
    try:
        media = MediaFileUpload(
            str(path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4"
        )
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"upload {int(status.progress() * 100)}%", flush=True)
    finally:
        youtube.close()

    vid = response.get("id")
    if not vid:
        raise UploadError(f"upload returned no id: {response}")
    return UploadResult(video_id=vid, url=f"https://youtu.be/{vid}", privacy=privacy)
