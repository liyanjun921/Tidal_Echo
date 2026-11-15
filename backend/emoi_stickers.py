"""Read image entries from an authenticated, owner-supplied sticker ZIP."""
import asyncio
import base64
import io
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, Request


MAX_ARCHIVE = 16 * 1024 * 1024
MAX_TOTAL = 24 * 1024 * 1024
MAX_IMAGE = 3 * 1024 * 1024
FORMATS = {
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    ".webp": ("image/webp", (b"RIFF",)),
}


def read_sticker_archive(data):
    stickers = []
    total = 0
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if member.is_dir() or any(part.startswith((".", "__MACOSX")) for part in path.parts):
                    continue
                spec = FORMATS.get(path.suffix.lower())
                if not spec:
                    continue
                if len(stickers) >= 500 or member.file_size > MAX_IMAGE:
                    raise HTTPException(422, "ZIP 最多 500 张图，每张最多 3 MB")
                total += member.file_size
                if total > MAX_TOTAL:
                    raise HTTPException(422, "ZIP 解压后的图片合计不能超过 24 MB")
                mime, signatures = spec
                image = archive.read(member)
                if not image.startswith(signatures) or mime == "image/webp" and image[8:12] != b"WEBP":
                    continue
                group = path.parent.name[:80] or "贴贴表情包"
                stickers.append({"name": path.name[:150], "pack": group, "mime": mime,
                                 "data": base64.b64encode(image).decode("ascii")})
    except (BadZipFile, RuntimeError, NotImplementedError, OSError, ValueError):
        raise HTTPException(422, "无法读取这个 ZIP 文件") from None
    if not stickers:
        raise HTTPException(422, "ZIP 中没有可导入的 PNG、JPG、GIF 或 WebP")
    return stickers


def register(app, check_auth):
    @app.post("/emoi/v2/stickers/unpack")
    async def unpack_stickers(request: Request):
        check_auth(request)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_ARCHIVE:
                raise HTTPException(413, "表情 ZIP 最大 16 MB")
            data.extend(chunk)
        return {"stickers": await asyncio.to_thread(read_sticker_archive, data)}
