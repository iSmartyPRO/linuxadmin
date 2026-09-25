"""File manager API. All paths are jailed to folders mounted in module settings."""

from __future__ import annotations

import asyncio
import mimetypes

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.principal import Principal, get_principal, require_module
from app.services import fileman
from app.services.persistence import get_modules

router = APIRouter(prefix="/api/files", tags=["files"])


class CheckPathBody(BaseModel):
    path: str = ""


class WriteBody(BaseModel):
    root_id: str
    rel: str
    content: str = Field(default="", max_length=8_000_000)


class NameBody(BaseModel):
    root_id: str
    rel: str = ""
    name: str = Field(min_length=1, max_length=255)


class MoveBody(BaseModel):
    root_id: str
    rel: str
    dest_rel: str = ""
    name: str | None = None


async def _mod(db: AsyncSession) -> dict:
    modules = await get_modules(db)
    mod = modules.get("files") or {}
    if not mod.get("enabled", True):
        raise HTTPException(status_code=403, detail="File Manager is disabled in settings")
    return mod


async def _call(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except fileman.FileManError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.post("/check-path")
async def check_path(
    body: CheckPathBody,
    principal: Principal = Depends(get_principal),
):
    if not (principal.can("files", "read") or principal.can("settings_modules", "full") or principal.can("settings_modules", "read")):
        raise HTTPException(status_code=403, detail="Missing permission")
    try:
        resolved = fileman.validate_root_path(body.path)
    except fileman.FileManError as exc:
        return {"ok": False, "error": exc.message}
    return {"ok": True, "path": resolved, "name": resolved.rstrip("/").split("/")[-1]}


@router.get("/browse")
async def browse_host(
    path: str = Query("/"),
    hidden: bool = Query(False),
    principal: Principal = Depends(get_principal),
):
    """Directory picker for module settings. Does not read file contents."""
    if not principal.can("settings_modules", "read"):
        raise HTTPException(status_code=403, detail="Missing permission")
    return await _call(fileman.browse_directories, path, show_hidden=hidden)


@router.get("/roots")
async def roots(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "read")),
):
    mod = await _mod(db)
    return {"roots": fileman.public_roots(mod), "allow_mutations": bool(mod.get("allow_mutations"))}


@router.get("/list")
async def list_directory(
    root_id: str = Query(min_length=1),
    rel: str = Query(""),
    hidden: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "read")),
):
    mod = await _mod(db)
    return await _call(fileman.list_dir, mod, root_id, rel, show_hidden=hidden)


@router.get("/text")
async def read_text(
    root_id: str = Query(min_length=1),
    rel: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "read")),
):
    mod = await _mod(db)
    return await _call(fileman.read_text, mod, root_id, rel)


@router.get("/raw")
async def read_raw(
    root_id: str = Query(min_length=1),
    rel: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "read")),
):
    mod = await _mod(db)
    path = await _call(fileman.read_raw_path, mod, root_id, rel)
    media, _enc = mimetypes.guess_type(path.name)
    # Never let the browser treat a downloaded file as an active HTML document.
    if media in {"text/html", "image/svg+xml", "application/xhtml+xml"}:
        media = "text/plain" if media != "image/svg+xml" else "image/svg+xml"
    return FileResponse(
        path,
        media_type=media or "application/octet-stream",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.put("/text")
async def write_text(
    body: WriteBody,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "full")),
):
    mod = await _mod(db)
    return await _call(fileman.write_text, mod, body.root_id, body.rel, body.content)


@router.post("/mkdir")
async def mkdir(
    body: NameBody,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "full")),
):
    mod = await _mod(db)
    return await _call(fileman.make_dir, mod, body.root_id, body.rel, body.name)


@router.post("/touch")
async def touch(
    body: NameBody,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "full")),
):
    mod = await _mod(db)
    return await _call(fileman.make_file, mod, body.root_id, body.rel, body.name)


@router.post("/move")
async def move(
    body: MoveBody,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "full")),
):
    mod = await _mod(db)
    return await _call(fileman.move_path, mod, body.root_id, body.rel, body.dest_rel, body.name)


@router.delete("/entry")
async def delete_entry(
    root_id: str = Query(min_length=1),
    rel: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "full")),
):
    mod = await _mod(db)
    return await _call(fileman.delete_path, mod, root_id, rel)


@router.post("/upload")
async def upload(
    root_id: str = Form(),
    rel: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_module("files", "full")),
):
    mod = await _mod(db)
    _preview, upload_cap = fileman._limits(mod)
    chunks: list[bytes] = []
    total = 0
    while True:
        buf = await file.read(1024 * 1024)
        if not buf:
            break
        total += len(buf)
        if total > upload_cap:
            raise HTTPException(status_code=413, detail="File is larger than the upload limit")
        chunks.append(buf)
    data = b"".join(chunks)
    return await _call(fileman.save_upload, mod, root_id, rel, file.filename or "upload", data)
