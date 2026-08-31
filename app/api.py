"""FastAPI endpoints.

/api/query is the simple synchronous entry point (full result in one response).
/api/query/stream is the SSE entry point the live trace panel uses: it streams a
"route" event as soon as the tier is decided, a "stage" event as each pipeline stage
finishes (or is marked skipped), and a final "done" event with results — driven by
LangGraph's own `.stream()`, not a fake progress bar.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select

from app.agent.graph import GraphState, get_compiled_graph, run_query
from app.db import get_session
from app.models import UserRecord
from app.personalization.profile_builder import build_user_profile
from app.personalization.temporal_patterns import current_context_boost, detect_recurring_patterns
from app.tracing import RoutingTrace

app = FastAPI(title="Agentic File Recommendation and Retrieval API")
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


@app.post("/api/query")
def query(req: QueryRequest):
    return run_query(req.query, req.user_id)


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

    return {
        "preferred_file_types": profile.preferred_file_types[:5],
        "top_files_by_frequency": sorted(
            profile.file_frequency.items(), key=lambda x: x[1], reverse=True
        )[:5],
        "recurring_patterns": [
            {
                "weekday": p.weekday_name,
                "hour": p.hour,
                "file_ids": p.file_ids,
                "confidence": round(p.confidence, 2),
            }
            for p in patterns
        ],
        "active_context_boost_now": active_boost,
    }
