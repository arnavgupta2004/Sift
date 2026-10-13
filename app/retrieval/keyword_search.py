"""BM25 keyword search over filename + extracted file content.

Usage:
    python -m app.retrieval.keyword_search "transformer training loop"
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from functools import lru_cache

from rank_bm25 import BM25Okapi
from sqlmodel import select

from app.db import DEFAULT_DB_PATH, get_engine, get_session
from app.models import FileRecord
from app.retrieval.base import ScoredFile

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class BM25Index:
    bm25: BM25Okapi
    file_ids: list[int]


@lru_cache(maxsize=1)
def build_index() -> BM25Index:
    """Filename tokens are repeated 3x in the indexed doc so a filename hit outranks a
    single incidental mention buried in body text, without a separate fusion step."""
    with get_session() as session:
        files = session.exec(select(FileRecord)).all()

    file_ids = []
    corpus = []
    for f in files:
        if f.id is None:
            continue
        filename_tokens = tokenize(f.filename) * 3
        body_tokens = tokenize(f.extracted_text)
        corpus.append(filename_tokens + body_tokens)
        file_ids.append(f.id)

    return BM25Index(bm25=BM25Okapi(corpus), file_ids=file_ids)


def _fts_ready(db_path=DEFAULT_DB_PATH) -> bool:
    try:
        with get_engine(db_path).connect() as conn:
            return conn.exec_driver_sql("SELECT 1 FROM files_fts LIMIT 1").first() is not None
    except Exception:
        return False


def _fts_search(query: str, limit: int, db_path=DEFAULT_DB_PATH) -> list[ScoredFile]:
    """BM25 over SQLite's FTS5 index, which the background indexer keeps current. Same
    ranking idea as the in-memory path (filename weighted 3x body) but it scales to a
    whole laptop's files and never needs rebuilding."""
    tokens = tokenize(query)
    if not tokens:
        return []
    match = " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens))
    with get_engine(db_path).connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT rowid, bm25(files_fts, 3.0, 1.0) FROM files_fts WHERE files_fts MATCH ? "
            "ORDER BY bm25(files_fts, 3.0, 1.0) LIMIT ?",
            (match, limit),
        ).fetchall()
    if not rows:
        return []
    best = max(-score for _, score in rows)  # FTS5 bm25() is lower-is-better and negative
    if best <= 0:
        return []
    return [
        ScoredFile(
            file_id=int(rowid),
            score=(-score) / best,
            source="keyword",
            explanation=f"BM25 keyword match, raw score {-score:.2f}",
        )
        for rowid, score in rows
        if -score > 0
    ]


def search(query: str, limit: int = 10) -> list[ScoredFile]:
    if _fts_ready():
        return _fts_search(query, limit)
    index = build_index()
    query_tokens = tokenize(query)
    if not query_tokens or not index.file_ids:
        return []

    scores = index.bm25.get_scores(query_tokens)
    max_score = max(scores) if len(scores) else 0.0
    if max_score <= 0:
        return []

    ranked = sorted(zip(index.file_ids, scores), key=lambda x: x[1], reverse=True)[:limit]
    return [
        ScoredFile(
            file_id=file_id,
            score=score / max_score,  # normalize to [0, 1] for fair fusion with other retrievers
            source="keyword",
            explanation=f"BM25 keyword match, raw score {score:.2f}",
        )
        for file_id, score in ranked
        if score > 0
    ]


def _main() -> None:
    parser = argparse.ArgumentParser(description="BM25 keyword search over the corpus DB.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    with get_session() as session:
        id_to_name = {f.id: f.filename for f in session.exec(select(FileRecord)).all()}

    for r in search(args.query, limit=args.limit):
        print(f"{r.score:.3f}  {id_to_name.get(r.file_id, '?')}  ({r.explanation})")


if __name__ == "__main__":
    _main()
