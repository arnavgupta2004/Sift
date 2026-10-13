"""FastAPI endpoints.

/api/query is the simple synchronous entry point (full result in one response).
/api/query/stream is the SSE entry point the live trace panel uses: it streams a
"route" event as soon as the tier is decided, a "stage" event as each pipeline stage
finishes (or is marked skipped), and a final "done" event with results — driven by
LangGraph's own `.stream()`, not a fake progress bar.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select

from app import indexer
from app.agent.graph import GraphState, get_compiled_graph, run_query
from app.db import DATA_DIR, get_session
from app.models import AccessEvent, FileRecord, UserRecord
from app.personalization.feedback import record_feedback
from app.personalization.profile_builder import build_user_profile
from app.personalization.temporal_patterns import current_context_boost, detect_recurring_patterns
from app.tracing import RoutingTrace

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_RESULTS_DIR = REPO_ROOT / "eval" / "results"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Sift searches the whole machine: indexing starts with the server and runs in the
    # background, so search works immediately and keeps getting better. Off for tests.
    if os.environ.get("SIFT_AUTO_INDEX", "1") != "0":
        indexer.start()
    yield
    indexer.stop()


app = FastAPI(title="Agentic File Recommendation and Retrieval API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class QueryRequest(BaseModel):
    query: str
    user_id: int


@app.get("/api/users")
def list_users():
    with get_session() as session:
        users = session.exec(select(UserRecord)).all()
    return [{"id": u.id, "name": u.name, "persona_key": u.persona_key} for u in users]


# Never launched from the UI, even if indexed: opening these would run code, not show a document.
_NEVER_OPEN = {"exe", "bat", "cmd", "com", "msi", "dll", "sh", "command", "app", "jar", "scr", "ps1", "vbs", "lnk", "pkg", "dmg"}
_LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")


@app.get("/api/me")
def me():
    """The one person who uses this laptop. Created on first run."""
    user_id = indexer.ensure_owner()
    with get_session() as session:
        user = session.get(UserRecord, user_id)
    return {"id": user.id, "name": user.name, "persona_key": user.persona_key}


@app.get("/api/index/status")
def index_status():
    return indexer.current_status()


class OpenRequest(BaseModel):
    file_id: int
    user_id: int | None = None


def _launch(path: Path) -> None:
    """Opens a file in the OS default app (this is a local-first app: the backend runs on
    the same machine as the user)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


@app.post("/api/open")
def open_file(req: OpenRequest, request: Request):
    """Opens an indexed file by id. Takes an id, not a path, so only files Sift has
    indexed can be opened, and only when the request comes from a local page."""
    origin = request.headers.get("origin")
    if origin and not _LOCAL_ORIGIN.match(origin):
        raise HTTPException(status_code=403, detail="files can only be opened from the local app")

    with get_session() as session:
        record = session.get(FileRecord, req.file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown file")
    if record.file_type.lower() in _NEVER_OPEN:
        raise HTTPException(status_code=403, detail=f".{record.file_type} files are not opened from here for safety")

    path = Path(record.path)
    if not path.is_absolute():
        path = DATA_DIR / "files_corpus" / record.path
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"file no longer exists: {path}")

    _launch(path)
    if req.user_id is not None:
        with get_session() as session:
            session.add(AccessEvent(
                user_id=req.user_id, file_id=record.id, action="open",
                timestamp=datetime.now(), session_id="ui",
            ))
            session.commit()
    return {"opened": str(path)}


@app.post("/api/query")
def query(req: QueryRequest):
    return run_query(req.query, req.user_id)


class FeedbackRequest(BaseModel):
    user_id: int
    file_id: int
    query: str
    signal: str  # "thumbs_up" | "thumbs_down" | "opened"


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    try:
        event = record_feedback(req.user_id, req.file_id, req.query, req.signal)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if req.signal in ("thumbs_up", "opened"):
        # A positive signal means "I use this file": it feeds the behavioral profile too.
        with get_session() as session:
            session.add(AccessEvent(
                user_id=req.user_id, file_id=req.file_id, action="open",
                timestamp=datetime.now(), session_id="ui-feedback",
            ))
            session.commit()
    return {"id": event.id, "recorded": True}


@app.get("/api/query/stream")
def query_stream(query: str, user_id: int):
    def event_generator():
        trace = RoutingTrace()
        initial_state: GraphState = {
            "query": query,
            "user_id": user_id,
            "now": datetime.now(),
            "trace": trace,
        }

        seen_stages = 0
        tier_emitted = False
        final_results = None

        for step in get_compiled_graph().stream(initial_state):
            node_name, partial = next(iter(step.items()))

            if not tier_emitted and trace.tier:
                yield _sse({"type": "route", "tier": trace.tier, "rationale": trace.rationale})
                tier_emitted = True

            while seen_stages < len(trace.stages):
                s = trace.stages[seen_stages]
                yield _sse({
                    "type": "stage",
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 2),
                    "skipped": s.skipped,
                    "detail": s.detail,
                })
                seen_stages += 1

            if node_name == "finalize":
                final_results = partial.get("final_results")

        yield _sse({"type": "done", "results": final_results, "routing_trace": trace.to_dict()})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/api/personalization/{user_id}")
def personalization_insights(user_id: int):
    now = datetime.now()
    profile = build_user_profile(user_id, now=now)
    patterns = detect_recurring_patterns(user_id)
    active_boost = current_context_boost(user_id, now=now)

    top_files = sorted(profile.file_frequency.items(), key=lambda x: x[1], reverse=True)[:5]
    all_file_ids = {fid for fid, _ in top_files} | {fid for p in patterns for fid in p.file_ids}
    with get_session() as session:
        records = session.exec(select(FileRecord).where(FileRecord.id.in_(all_file_ids))).all()
    name_by_id = {r.id: r.filename for r in records}

    return {
        "preferred_file_types": profile.preferred_file_types[:5],
        "top_files_by_frequency": [
            {"file_id": fid, "filename": name_by_id.get(fid, "?"), "frequency": round(freq, 3)}
            for fid, freq in top_files
        ],
        "recurring_patterns": [
            {
                "weekday": p.weekday_name,
                "hour": p.hour,
                "file_ids": p.file_ids,
                "filenames": [name_by_id.get(fid, "?") for fid in p.file_ids],
                "confidence": round(p.confidence, 2),
            }
            for p in patterns
        ],
        "active_context_boost_now": bool(active_boost),
        "active_context_files": [name_by_id.get(fid, "?") for fid in active_boost] if active_boost else [],
    }


@app.get("/api/eval/baseline-comparison")
def baseline_comparison():
    path = EVAL_RESULTS_DIR / "baseline_comparison_summary.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="run eval/baseline_comparison.py first")
    return json.loads(path.read_text())
