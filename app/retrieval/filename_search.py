"""Fuzzy filename/path matching — the sole retriever on the fast route.

Deliberately has zero dependency on embeddings, BM25 index state, or the LLM: this is
what makes the fast-route latency claim in eval/latency_comparison.py honest.

Usage:
    python -m app.retrieval.filename_search "q3 revenue report"
"""

from __future__ import annotations

import argparse

from rapidfuzz import fuzz, process
from sqlalchemy import func
from sqlmodel import select

from app.db import get_session
from app.models import FileRecord
from app.retrieval.base import ScoredFile


def exact_match(filename: str) -> ScoredFile | None:
    """Direct DB lookup for a filename already recognized as an exact pattern by
    query_understanding.py (case-insensitive). Used instead of relying on fuzzy
    matching of the whole query sentence, which can rank a similarly-named file above
    the one actually named — see app/agent/graph.py node_fast_retrieve."""
    with get_session() as session:
        rec = session.exec(
            select(FileRecord).where(FileRecord.filename.ilike(filename))
        ).first()
    if rec is None or rec.id is None:
        return None
    return ScoredFile(
        file_id=rec.id, score=1.0, source="filename", explanation=f"exact filename match: '{filename}'"
    )


_choices_cache: dict = {"key": None, "choices": {}}


def _choices() -> dict[int, str]:
    """id -> "filename path" for every file. Reads only those three columns (never the
    extracted text) and is cached until the set of files changes, because on a real
    laptop this is hundreds of thousands of rows and runs on every query."""
    with get_session() as session:
        key = tuple(session.exec(select(func.count(FileRecord.id), func.max(FileRecord.id))).one())
        if _choices_cache["key"] == key:
            return _choices_cache["choices"]
        rows = session.exec(select(FileRecord.id, FileRecord.filename, FileRecord.path)).all()
    choices = {fid: f"{name} {path}" for fid, name, path in rows if fid is not None}
    _choices_cache["key"], _choices_cache["choices"] = key, choices
    return choices


def search(query: str, limit: int = 10, score_cutoff: float = 45.0) -> list[ScoredFile]:
    """Fuzzy-matches `query` against filename (weighted higher) and full path.
    score_cutoff is on rapidfuzz's 0-100 scale; results are returned with score in [0, 1].
    """
    choices = _choices()
    if not choices:
        return []

    matches = process.extract(
        query, choices, scorer=fuzz.WRatio, score_cutoff=score_cutoff, limit=limit,
    )

    results = []
    for matched_text, score, file_id in matches:
        results.append(
            ScoredFile(
                file_id=file_id,
                score=score / 100.0,
                source="filename",
                explanation=f"filename/path fuzzy-matched '{query}' ({score:.0f}/100)",
            )
        )
    return results


def _main() -> None:
    parser = argparse.ArgumentParser(description="Fuzzy filename search over the corpus DB.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    with get_session() as session:
        id_to_name = {f.id: f.filename for f in session.exec(select(FileRecord)).all()}

    for r in search(args.query, limit=args.limit):
        print(f"{r.score:.3f}  {id_to_name.get(r.file_id, '?')}  ({r.explanation})")


if __name__ == "__main__":
    _main()
