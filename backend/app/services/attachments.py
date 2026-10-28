"""Screenshots attached to a problem report (a revision request).

Images arrive as data URLs from the browser (pasted, dropped or picked). Each
one is decoded and checked by its actual bytes — not its name or claimed type
— and only PNG, JPEG, GIF and WebP up to MAX_BYTES are kept. They are stored
outside every workspace (so they are never committed) under
<data>/attachments/<workflow id>/<n>.<ext>, and served back by exact name.
"""
from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path

from app.core.config import settings

MAX_IMAGES = 5
MAX_BYTES = 5 * 1024 * 1024
_DATA_URL = re.compile(r"^data:(image/[a-z+.-]+);base64,([A-Za-z0-9+/=\s]+)$")
_NAME = re.compile(r"^\d{1,2}\.(png|jpg|gif|webp)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


class AttachmentError(ValueError):
    """User-facing: the attachment was refused."""


def _sniff(data: bytes) -> str | None:
    """The image format from its leading bytes, or None if it isn't one we accept."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def decode(data_urls: list[str]) -> list[tuple[str, bytes]]:
    """Validate every image before anything is stored: (extension, bytes) each."""
    if len(data_urls) > MAX_IMAGES:
        raise AttachmentError(f"Attach at most {MAX_IMAGES} screenshots.")
    images = []
    for i, url in enumerate(data_urls, start=1):
        match = _DATA_URL.match(url.strip())
        if not match:
            raise AttachmentError(f"Screenshot {i} is not an image.")
        try:
            data = base64.b64decode(match.group(2), validate=False)
        except (binascii.Error, ValueError) as exc:
            raise AttachmentError(f"Screenshot {i} could not be read.") from exc
        if len(data) > MAX_BYTES:
            raise AttachmentError(f"Screenshot {i} is larger than {MAX_BYTES // (1024 * 1024)} MB.")
        kind = _sniff(data)
        if kind is None:
            raise AttachmentError(f"Screenshot {i} must be a PNG, JPEG, GIF or WebP image.")
        images.append((kind, data))
    return images


def _folder(workflow_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", workflow_id):
        raise AttachmentError("Invalid workflow id.")
    return Path(settings.workspaces_dir).parent / "attachments" / workflow_id


def save(workflow_id: str, images: list[tuple[str, bytes]]) -> list[str]:
    """Store the images; returns their file names."""
    folder = _folder(workflow_id)
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for i, (kind, data) in enumerate(images, start=1):
        name = f"{i}.{kind}"
        (folder / name).write_bytes(data)
        names.append(name)
    return names


def path_for(workflow_id: str, name: str) -> Path | None:
    """The stored file for an exact attachment name, or None."""
    if not _NAME.fullmatch(name):
        return None
    path = _folder(workflow_id) / name
    return path if path.is_file() else None


def remove_all(workflow_id: str) -> None:
    import shutil

    folder = _folder(workflow_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
