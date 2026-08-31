# Agentic File Recommendation and Retrieval System

An agentic file-search system that understands a natural-language query, decides *which* retrieval
strategies it actually needs (filename/fuzzy, metadata, keyword BM25, semantic embeddings, or a hybrid
of these), personalizes results to the requesting user's behavioral history, and explains its own
ranking decisions — instead of always running one fixed RAG pipeline.

> **Status: core system complete (build-order phases 1-9).** Extended scope (learned personalization
> ranker, learned router, real-data connector, production React/TS UI, Docker + CI, full written report)
> is tracked separately. Everything below is real, run, and verified — not aspirational.

## Headline numbers

Full methodology and every chart: **[`eval/RESULTS.md`](eval/RESULTS.md)**. All reproducible via the
commands in that file.

- **Routing saves 5.5x mean latency overall** (23.8x on simple/exact queries) for a stated **−0.033
  NDCG@10** quality cost — the router is a real, quantified tradeoff, not a free lunch.
- **The full system beats naive keyword-only and semantic-only baselines** on NDCG@10 (0.557 vs. 0.470
  / 0.493) and MRR (0.644 vs. 0.514 / 0.556), while running 5.7x faster than the always-full-pipeline
  agent it's built on.
- **Hybrid RRF fusion nearly doubles NDCG@10** over naively concatenating retriever results (0.277 →
  0.481) — genuine rank fusion, not just "more retrievers," is what earns the gain.
- **Personalization's hand-tuned baseline shows a small negative lift** (−0.016 NDCG@10 against users'
  own access history) — reported honestly, not adjusted to look better, and used as the motivation for
  the learned (LightGBM) ranker in the extended-scope phase.

## Why this exists (the three objectives)

| Objective | What it means | Where it lives |
|---|---|---|
| **1. Intelligent Discovery** | Understand intent, choose retrieval strategy/strategies, retrieve, rank, explain each result in natural language. | `app/agent/query_understanding.py`, `app/retrieval/` |
| **2. Personalization** | Build a per-user behavioral profile (frequency, recency, topic affinity, temporal/session patterns) from an access log and use it to re-rank results. | `app/personalization/` |
| **3. Agentic Routing** | Classify query complexity and route through the cheapest sufficient pipeline (fast / standard / deep), with measured latency savings vs. an always-full-pipeline baseline. | `app/agent/router.py`, `eval/latency_comparison.py` |

Every response the system returns includes a `routing_trace`: which tier was chosen, which components
ran (and which were skipped), per-component latency, and a one-line rationale for the routing decision.
This isn't a debug log — it's a first-class API field (`app/tracing.py`) and it's what the live SSE
stream (`GET /api/query/stream`) and the dev UI's trace panel render in real time.

## Architecture

```
                        Query (NL)
                            |
                 Query Understanding (rule-based,
                 always; LLM enrichment on deep only)
                            |
                    Complexity Router
              (rule-based first, LLM fallback
               only for genuinely ambiguous queries)
                            |
        +-------------------+-------------------+
        |                   |                   |
     FAST                STANDARD              DEEP
  filename +         metadata + keyword    metadata + keyword
  metadata only        + semantic           + semantic
  (RRF fusion)        (RRF fusion)          (RRF fusion)
        |                   |                   |
        |                   |            Cross-encoder rerank
        |                   |                   |
        +-------------------+-------------------+
                            |
              Personalization re-rank (skipped for
              exact-filename queries — see below)
                            |
                 [LLM explanation — deep only]
                            |
                  Results + routing_trace
```

Explicit LangGraph nodes and edges (`app/agent/graph.py`) — inspectable, not a hidden agent loop.
Two things worth knowing if you read the code:

- **Personalization is skipped when the query names an exact filename.** Typing a literal filename is a
  deterministic ask; letting personalization reorder it based on unrelated user history was a real bug
  we found via the eval harness (see `eval/RESULTS.md` §1) and fixed with a regression test.
- **Every tier pays for rule-based entity extraction; only the deep tier can pay for LLM query
  enrichment; only borderline-complexity queries pay for an LLM routing-classification call.** This is
  what makes the fast route's "zero LLM calls" claim in the eval results literally true, not just
  approximately true.

## Repository layout

```
Agentic-AI-Project/
├── data/
│   ├── generate_synthetic_data.py  # single reproducible entry point (corpus + DB + access log)
│   ├── synth/                      # topics, personas, content generation, access-log simulation
│   └── files_corpus/, db.sqlite    # generated, gitignored — not checked in
├── app/
│   ├── agent/       # graph.py (LangGraph), router.py, query_understanding.py, explain.py
│   ├── retrieval/   # filename, metadata, keyword, semantic, hybrid_fusion (RRF from scratch), reranker
│   ├── personalization/  # profile_builder, temporal_patterns, personalized_ranker
│   ├── api.py       # FastAPI: /api/query, /api/query/stream (SSE), /api/users, /api/personalization
│   ├── llm_client.py  # single chokepoint for all LLM calls (Gemini-backed; see note below)
│   ├── models.py    # shared SQLModel schema
│   └── tracing.py   # RoutingTrace — the first-class per-stage timing object
├── ui/
│   └── streamlit_app.py  # internal-iteration dev UI (throwaway — see build order)
├── eval/
│   ├── build_eval_set.py, metrics.py, run_benchmark.py
│   ├── ablation_study.py, latency_comparison.py, baseline_comparison.py, personalization_lift.py
│   ├── eval_set.json     # 49 labeled queries, checked in
│   ├── RESULTS.md        # full write-up, every number sourced from results/
│   └── results/           # CSVs, JSON summaries, PNG charts — all regeneratable, checked in
└── tests/            # 74 pytest cases across every component
```

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python data/generate_synthetic_data.py   # builds the corpus + DB + access log from scratch
python eval/build_eval_set.py            # builds the labeled eval set against that corpus

pytest                                    # 74 tests

streamlit run ui/streamlit_app.py         # internal dev UI
# or:
uvicorn app.api:app --reload              # API only (POST /api/query, GET /api/query/stream)
```

### LLM backend

This project was specced against the Claude API but built against **Gemini** (the credential actually
available). Every LLM call is isolated behind `app/llm_client.py`, which is intentionally
provider-agnostic — swapping backends only touches that one file. Set `GEMINI_API_KEY` in a `.env` file
(copy `.env.example`) to enable LLM-backed query enrichment, routing-classification fallback, and
richer synthetic-content generation. **The system runs completely end-to-end without this set** —
every LLM-gated step has a rule-based fallback, which is what all the eval numbers in this repo were
run against (no API key was available in the build environment).

## Reproducing every claim

Every quantitative claim in this README and in `eval/RESULTS.md` is produced by a script under `eval/`
that can be re-run from scratch — no numbers here are hand-typed without a corresponding script.
