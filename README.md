# Agentic File Recommendation and Retrieval System

An agentic file-search system that understands a natural-language query, decides *which* retrieval
strategies it actually needs (filename/fuzzy, metadata, keyword BM25, semantic embeddings, or a hybrid
of these), personalizes results to the requesting user's behavioral history, and explains its own
ranking decisions — instead of always running one fixed RAG pipeline.

> **Status: early scaffold.** This README will be filled in with headline eval numbers, architecture
> details, and run instructions as each phase lands. See `eval/RESULTS.md` (once populated) for the
> reproducible numbers behind every claim below.

## Why this exists (the three objectives)

| Objective | What it means | Where it lives |
|---|---|---|
| **1. Intelligent Discovery** | Understand intent, choose retrieval strategy/strategies, retrieve, rank, explain each result in natural language. | `app/agent/query_understanding.py`, `app/retrieval/` |
| **2. Personalization** | Build a per-user behavioral profile (frequency, recency, topic affinity, temporal/session patterns) from an access log and use it to re-rank results. | `app/personalization/` |
| **3. Agentic Routing** | Classify query complexity and route through the cheapest sufficient pipeline (fast / standard / deep), with measured latency savings vs. an always-full-pipeline baseline. | `app/agent/router.py`, `eval/latency_comparison.py` |

Every response the system returns includes a `routing_trace`: which tier was chosen, which components
ran (and which were skipped), per-component latency, and a one-line rationale for the routing decision.

## Architecture

```
Query -> Query Understanding (LLM) -> Complexity Router -> [fast | standard | deep] retrieval
      -> Hybrid Fusion (RRF) -> [Reranker] -> Personalization re-rank -> [LLM explanation] -> Results + trace
```

Full diagram and per-node description: see the architecture section below (filled in as the LangGraph
graph is implemented in `app/agent/graph.py`).

## Repository layout

```
Agentic-AI-Project/
├── data/            # synthetic corpus + access log generation
├── app/
│   ├── agent/       # LangGraph state graph, router, query understanding, explanation
│   ├── retrieval/   # filename, metadata, keyword, semantic, hybrid fusion, reranker
│   └── personalization/
├── ui/              # frontend (Streamlit prototype -> React/TS production UI)
├── eval/            # benchmark harness, ablations, baselines, checked-in results
└── tests/           # unit tests per component
```

## Running it

Setup and run instructions will be added as each phase lands (data generation first). See
`data/generate_synthetic_data.py` once present for the first reproducible entry point.

## Reproducing every claim

Every quantitative claim in this README and in `eval/RESULTS.md` is produced by a script under `eval/`
that can be re-run from scratch — no numbers here are hand-typed without a corresponding script.
