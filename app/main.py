from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import (
    create_document,
    delete_document,
    get_document,
    get_stats,
    init_db,
    list_documents,
    list_qa_logs,
    rebuild_chunks,
    save_qa_log,
    search_chunks,
    update_feedback,
)
from .rag import extract_text_from_file, normalize_text, synthesize_answer


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"

app = FastAPI(
    title="Document RAG QA System",
    description="企业知识库文档问答系统，支持文档上传、文本切分、向量检索、引用来源、问答日志和用户反馈。",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class TextDocumentRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=80)
    content: str = Field(..., min_length=20)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)
    top_k: int = Field(default=5, ge=1, le=10)


class FeedbackRequest(BaseModel):
    feedback: str = Field(..., pattern="^(useful|bad)$")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/logs")
def logs_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "logs.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/stats")
def stats() -> dict:
    return get_stats()


@app.get("/api/documents")
def documents() -> dict:
    return {"items": list_documents()}


@app.get("/api/documents/{document_id}")
def document_detail(document_id: int) -> dict:
    document = get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    return document


@app.post("/api/documents/text")
def create_text_document(payload: TextDocumentRequest) -> dict:
    document = create_document(
        title=payload.title.strip(),
        filename="manual-input.txt",
        file_type="text",
        content=normalize_text(payload.content),
    )
    return document


@app.post("/api/documents/upload")
async def upload_document(
    request: Request,
    x_filename: str = Header(default="uploaded.txt"),
    x_title: Optional[str] = Header(default=None),
) -> dict:
    x_filename = unquote(x_filename)
    x_title = unquote(x_title) if x_title else None
    suffix = Path(x_filename).suffix.lower()
    if suffix not in {".txt", ".md", ".csv", ".json", ".pdf"}:
        raise HTTPException(status_code=400, detail="only txt, md, csv, json, pdf files are supported")

    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await request.body())
        tmp_path = Path(tmp.name)

    try:
        content = normalize_text(extract_text_from_file(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    if len(content) < 20:
        raise HTTPException(status_code=400, detail="document content is too short")

    document = create_document(
        title=(x_title or Path(x_filename).stem or "未命名文档").strip(),
        filename=x_filename,
        file_type=suffix.lstrip("."),
        content=content,
    )
    return document


@app.post("/api/documents/{document_id}/rebuild")
def rebuild_document(document_id: int) -> dict:
    document = get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    chunk_count = rebuild_chunks(document_id, document["content"])
    return {"document_id": document_id, "chunk_count": chunk_count}


@app.delete("/api/documents/{document_id}")
def remove_document(document_id: int) -> dict:
    deleted = delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")
    return {"deleted": True}


@app.post("/api/ask")
def ask(payload: AskRequest) -> dict:
    hits = search_chunks(payload.question, payload.top_k)
    answer_data = synthesize_answer(payload.question, hits)
    log_id = save_qa_log(
        payload.question,
        answer_data["answer"],
        answer_data["confidence"],
        answer_data["sources"],
    )
    return {"id": log_id, "question": payload.question, **answer_data}


@app.get("/api/logs")
def qa_logs(limit: int = 30) -> dict:
    limit = max(1, min(limit, 100))
    return {"items": list_qa_logs(limit)}


@app.post("/api/logs/{log_id}/feedback")
def feedback(log_id: int, payload: FeedbackRequest) -> dict:
    updated = update_feedback(log_id, payload.feedback)
    if not updated:
        raise HTTPException(status_code=404, detail="log not found")
    return {"updated": True, "feedback": payload.feedback}
