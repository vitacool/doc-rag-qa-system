import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .rag import SearchHit, cosine, embed_text, make_chunks, vector_from_json, vector_to_json


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "knowledge_base.db"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT,
                file_type TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS qa_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                confidence REAL NOT NULL,
                sources_json TEXT NOT NULL,
                feedback TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


def rebuild_chunks(document_id: int, content: str) -> int:
    chunks = make_chunks(document_id, content)
    with get_connection() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.executemany(
            """
            INSERT INTO chunks (document_id, chunk_index, content, vector_json, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.document_id,
                    chunk.chunk_index,
                    chunk.content,
                    vector_to_json(chunk.vector),
                    chunk.token_count,
                    now(),
                )
                for chunk in chunks
            ],
        )
        conn.execute(
            "UPDATE documents SET chunk_count = ?, status = ?, updated_at = ? WHERE id = ?",
            (len(chunks), "indexed", now(), document_id),
        )
        conn.commit()
    return len(chunks)


def create_document(title: str, filename: str, file_type: str, content: str) -> Dict:
    timestamp = now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO documents (title, filename, file_type, content, status, chunk_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, filename, file_type, content, "pending", 0, timestamp, timestamp),
        )
        document_id = int(cursor.lastrowid)
        conn.commit()
    chunk_count = rebuild_chunks(document_id, content)
    return get_document(document_id) | {"chunk_count": chunk_count}


def list_documents() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, filename, file_type, status, chunk_count, created_at, updated_at
            FROM documents
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_document(document_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, title, filename, file_type, content, status, chunk_count, created_at, updated_at
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_document(document_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.commit()
    return cursor.rowcount > 0


def search_chunks(question: str, top_k: int = 5) -> List[SearchHit]:
    query_vector = embed_text(question)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT chunks.id AS chunk_id, chunks.document_id, documents.title, chunks.chunk_index,
                   chunks.content, chunks.vector_json
            FROM chunks
            JOIN documents ON documents.id = chunks.document_id
            """
        ).fetchall()

    hits = []
    for row in rows:
        score = cosine(query_vector, vector_from_json(row["vector_json"]))
        if score <= 0:
            continue
        hits.append(
            SearchHit(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                title=row["title"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                score=score,
            )
        )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:top_k]


def save_qa_log(question: str, answer: str, confidence: float, sources: List[Dict]) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO qa_logs (question, answer, confidence, sources_json, feedback, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (question, answer, confidence, json.dumps(sources, ensure_ascii=False), None, now()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_qa_logs(limit: int = 30) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, question, answer, confidence, sources_json, feedback, created_at
            FROM qa_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "question": row["question"],
            "answer": row["answer"],
            "confidence": row["confidence"],
            "sources": json.loads(row["sources_json"]),
            "feedback": row["feedback"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def update_feedback(log_id: int, feedback: str) -> bool:
    if feedback not in {"useful", "bad"}:
        raise ValueError("feedback must be useful or bad")
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE qa_logs SET feedback = ? WHERE id = ?",
            (feedback, log_id),
        )
        conn.commit()
    return cursor.rowcount > 0


def get_stats() -> Dict:
    with get_connection() as conn:
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        qa_count = conn.execute("SELECT COUNT(*) FROM qa_logs").fetchone()[0]
        useful_count = conn.execute("SELECT COUNT(*) FROM qa_logs WHERE feedback = 'useful'").fetchone()[0]
        bad_count = conn.execute("SELECT COUNT(*) FROM qa_logs WHERE feedback = 'bad'").fetchone()[0]
    return {
        "documents": doc_count,
        "chunks": chunk_count,
        "qa_logs": qa_count,
        "useful_feedback": useful_count,
        "bad_feedback": bad_count,
    }
