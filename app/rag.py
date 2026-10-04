import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


VECTOR_DIM = 256
STOPWORDS = {
    "的",
    "了",
    "和",
    "是",
    "在",
    "对",
    "与",
    "及",
    "或",
    "the",
    "and",
    "of",
    "to",
    "in",
    "for",
    "a",
    "an",
    "is",
    "are",
}


@dataclass
class Chunk:
    document_id: int
    chunk_index: int
    content: str
    vector: List[float]
    token_count: int


@dataclass
class SearchHit:
    chunk_id: int
    document_id: int
    title: str
    chunk_index: int
    content: str
    score: float


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise RuntimeError("PDF 解析需要安装 pypdf：pip install pypdf") from exc
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    raise ValueError("仅支持 txt、md、csv、json、pdf 文件")


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", normalize_text(text))
    return [part.strip() for part in parts if part.strip()]


def chunk_text(text: str, max_chars: int = 520, overlap: int = 80) -> List[str]:
    sentences = split_sentences(text)
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current}\n{sentence}".strip()
            continue
        if current:
            chunks.append(current)
        current = sentence
    if current:
        chunks.append(current)

    merged: List[str] = []
    for chunk in chunks:
        if not merged:
            merged.append(chunk)
            continue
        if len(chunk) < 120 and len(merged[-1]) + len(chunk) <= max_chars:
            merged[-1] = f"{merged[-1]}\n{chunk}"
        else:
            prefix = merged[-1][-overlap:] if overlap > 0 else ""
            merged.append(f"{prefix}\n{chunk}".strip())
    return merged or [normalize_text(text)]


def tokenize(text: str) -> List[str]:
    lowered = text.lower()
    english = re.findall(r"[a-z][a-z0-9+#.]{1,}", lowered)
    chinese_words = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    chinese_bigrams = [
        word[i : i + 2]
        for word in chinese_words
        for i in range(max(0, len(word) - 1))
    ]
    terms = english + chinese_bigrams
    return [term for term in terms if term not in STOPWORDS]


def hash_term(term: str) -> int:
    digest = hashlib.md5(term.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % VECTOR_DIM


def embed_text(text: str) -> List[float]:
    tokens = tokenize(text)
    vector = [0.0] * VECTOR_DIM
    if not tokens:
        return vector
    counts = Counter(tokens)
    for term, count in counts.items():
        vector[hash_term(term)] += 1.0 + math.log(count)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def vector_to_json(vector: Sequence[float]) -> str:
    return json.dumps(list(vector), separators=(",", ":"))


def vector_from_json(raw: str) -> List[float]:
    return [float(value) for value in json.loads(raw)]


def make_chunks(document_id: int, text: str) -> List[Chunk]:
    chunks = []
    for index, content in enumerate(chunk_text(text), start=1):
        chunks.append(
            Chunk(
                document_id=document_id,
                chunk_index=index,
                content=content,
                vector=embed_text(content),
                token_count=len(tokenize(content)),
            )
        )
    return chunks


def important_terms(question: str) -> List[str]:
    counts = Counter(tokenize(question))
    return [term for term, _ in counts.most_common(8)]


def score_sentence(sentence: str, terms: Iterable[str]) -> int:
    lowered = sentence.lower()
    return sum(1 for term in terms if term in lowered)


def synthesize_answer(question: str, hits: List[SearchHit]) -> Dict:
    if not hits:
        return {
            "answer": "知识库中暂时没有检索到足够相关的内容，可以先补充文档或换一种问法。",
            "confidence": 0.0,
            "sources": [],
        }

    terms = important_terms(question)
    candidate_sentences = []
    for hit in hits[:4]:
        for sentence in split_sentences(hit.content):
            candidate_sentences.append((score_sentence(sentence, terms), hit.score, sentence, hit))

    candidate_sentences.sort(key=lambda item: (item[0], item[1], len(item[2])), reverse=True)
    selected = []
    seen = set()
    for _, _, sentence, hit in candidate_sentences:
        compact = sentence[:80]
        if compact in seen:
            continue
        selected.append((sentence, hit))
        seen.add(compact)
        if len(selected) >= 3:
            break

    if not selected:
        selected = [(hits[0].content[:260], hits[0])]

    bullets = [f"{index}. {sentence}" for index, (sentence, _) in enumerate(selected, start=1)]
    answer = "根据知识库检索结果，可以这样回答：\n" + "\n".join(bullets)
    source_map = {}
    for _, hit in selected:
        key = f"{hit.document_id}-{hit.chunk_index}"
        source_map[key] = {
            "document_id": hit.document_id,
            "title": hit.title,
            "chunk_index": hit.chunk_index,
            "score": round(hit.score, 4),
            "preview": hit.content[:180],
        }

    return {
        "answer": answer,
        "confidence": round(max(hit.score for hit in hits), 4),
        "sources": list(source_map.values()),
    }
