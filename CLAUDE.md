# CLAUDE.md

Do not include a Co-Authored-By line or any Claude/AI attribution in commit messages, ever.

## Project

Agentic File Recommendation and Retrieval System — course capstone. See [README.md](README.md) for
architecture, setup, and eval results. Full spec history and phase plan tracked in project memory,
not in this file.

## Conventions

- Python 3.11+ (repo developed against 3.13; no version-specific features used beyond 3.11 baseline).
- Backend: FastAPI + LangGraph, under `app/`.
- Frontend: React + TypeScript (Vite), under `ui/` (Streamlit prototype first, replaced later per build order).
- Every retrieval/personalization/routing component must be independently testable via CLI and covered
  by a unit test in `tests/`.
- Every claim in the README/report must map to a script under `eval/` that reproduces the number.
