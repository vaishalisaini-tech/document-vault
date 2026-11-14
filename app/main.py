import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import build_engine
from app.logging_config import setup_logging
from app.models import Document
from app.schemas import DocumentCreate, DocumentOut
import os, re, uuid
from fastapi import BackgroundTasks, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool
from app.storage import StorageService


setup_logging()
log = logging.getLogger("document-vault")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine, connector = await build_engine()
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    app.state.storage = StorageService(settings.gcs_bucket, settings.signer_sa_email)
    log.info("database pool ready")
    yield
    await engine.dispose()
    await connector.close_async()
    log.info("database pool closed")

app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan)

async def get_session(request: Request):
    async with request.app.state.sessionmaker() as session:
        yield session

def get_storage(request: Request) -> StorageService:
    return request.app.state.storage

@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "up", "env": settings.app_env}
    except Exception:
        log.exception("db health check failed")
        raise HTTPException(503, "database unavailable")

@app.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(body: DocumentCreate, session: AsyncSession = Depends(get_session)):
    doc = Document(**body.model_dump())
    session.add(doc)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "A document with this gcs_path already exists")
    await session.refresh(doc)
    return doc

@app.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    owner: str | None = None,
    tag: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
    if owner:
        stmt = stmt.where(Document.owner == owner)
    if tag:
        stmt = stmt.where(Document.tags.contains([tag.strip().lower()]))
    result = await session.scalars(stmt)
    return result.all()

@app.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: int, session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc

@app.delete("/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: int,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
):
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    object_name = storage.object_name(doc.gcs_path)
    await session.delete(doc)
    await session.commit()
    background.add_task(storage.delete, object_name)   # runs after the 204 is sent

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")

@app.post("/documents/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    owner: str = Form(..., min_length=2, max_length=100),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
):
    # 1. Validate size
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size == 0:
        raise HTTPException(400, "Empty file")
    if size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")

    # 2. Safe, unique object name
    original = os.path.basename(file.filename or "file")
    safe = SAFE_NAME.sub("_", original)[:200]
    object_name = f"{owner}/{uuid.uuid4().hex}-{safe}"
    content_type = file.content_type or "application/octet-stream"

    # 3. Upload to GCS FIRST (sync client → threadpool)
    await run_in_threadpool(storage.upload, file.file, object_name, content_type)

    # 4. Then the DB row; undo the upload if this fails
    doc = Document(owner=owner, filename=original, gcs_path=storage.gcs_uri(object_name),
                   size_bytes=size, content_type=content_type)
    session.add(doc)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await run_in_threadpool(storage.delete, object_name)
        log.exception("db insert failed; uploaded object removed")
        raise HTTPException(500, "Could not save document")
    await session.refresh(doc)
    return doc

@app.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: int,
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
):
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    url = await run_in_threadpool(
        storage.signed_download_url,
        storage.object_name(doc.gcs_path), doc.filename, settings.signed_url_minutes,
    )
    return {"url": url, "expires_in_seconds": settings.signed_url_minutes * 60}


