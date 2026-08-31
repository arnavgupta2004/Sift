"""Fuzzy filename/path matching — the sole retriever on the fast route.

Deliberately has zero dependency on embeddings, BM25 index state, or the LLM: this is
what makes the fast-route latency claim in eval/latency_comparison.py honest.

Usage:
    python -m app.retrieval.filename_search "q3 revenue report"
"""

from __future__ import annotations

import argparse

from rapidfuzz import fuzz, process
from sqlmodel import select

from app.db import get_session
from app.models import FileRecord
from app.retrieval.base import ScoredFile


def search(query: str, limit: int = 10, score_cutoff: float = 45.0) -> list[ScoredFile]:
    """Fuzzy-matches `query` against filename (weighted higher) and full path.
    score_cutoff is on rapidfuzz's 0-100 scale; results are returned with score in [0, 1].
    """
    with get_session() as session:
        files = session.exec(select(FileRecord)).all()

    if not files:
        return []

    choices = {f.id: f"{f.filename} {f.path}" for f in files if f.id is not None}
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
