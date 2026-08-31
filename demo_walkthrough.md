# Demo walkthrough

A scripted run-through for presenting Sift live, covering all three routing tiers plus
the real-data connector. ~8-10 minutes.

## Setup (before the audience arrives)

```bash
# from repo root
pip install -r requirements.txt
python data/generate_synthetic_data.py
python eval/build_eval_set.py
python -m app.retrieval.semantic_search --build   # warm the embedding index once

# two terminals:
uvicorn app.api:app --reload            # terminal 1
cd ui/frontend && npm install && npm run dev   # terminal 2
```

Open `http://localhost:5173`. If you have `GEMINI_API_KEY` set (copy `.env.example` →
`.env`), the deep-route queries below will show real LLM-generated explanations and
query enrichment; without it, they fall back to rule-based explanations — say so
explicitly rather than letting it look broken.

Run each of the three queries below **once** before presenting, so the sentence-
transformer and cross-encoder models are warm (cold start is ~15-25s on first call;
warm is under a second for fast/standard, a couple seconds for deep).

## 1. Fast route — "this should feel instant"

Pick any real filename from your corpus and type:

```
open <some_filename>.docx
```

Point out on the trace panel: **filename search** and **metadata search** run,
**everything else is greyed out** — keyword, semantic, reranker, personalization,
explanation all skipped. Total latency should be single-digit milliseconds. Say the
number out loud; it's the whole point of Objective 3.

## 2. Standard route — "moderately specific, no reranker"

```
find my recent notes about transformers
```

Point out: metadata + keyword + semantic all ran, RRF fusion combined them,
personalization re-ranked — but the reranker and LLM explanation are still greyed
out. This is the tier that's "pretty sure but doesn't need the expensive pass."

## 3. Deep route — "this is where the agent actually reasons"

```
find that thing I was working on with my advisor about audio deepfakes a few weeks ago
```

Every stage lights up, including the cross-encoder reranker and (with a key set) the
LLM explanation. Read one of the explanations out loud — it should be a genuine
sentence about *why* that file matches, not a template. Switch the user dropdown
(top of the query bar) and re-run the same query: the ranking changes because
personalization is now blending in a different user's access history — point at the
score breakdown to show the base-vs-personalization split.

## 4. Real data, live

```bash
python data/ingest_datasource.py --root . --max-files 30
```

(Run this against the Sift repo itself, or any directory you're comfortable showing —
see `data/ingest_datasource.py`'s docstring; it defaults to adding real files
alongside the synthetic corpus, not replacing it.) Then in the UI:

```
open retrain.py
```

or, if you pointed it somewhere with real prose, a natural-language query about that
content. This is not a pre-baked demo file — it's the same pipeline finding a file
that didn't exist in the system five seconds ago.

## 5. The receipts

Scroll to the **baseline comparison** panel and narrate the four bars: naive
keyword-only, naive semantic-only ("what a lazy RAG wrapper looks like"),
always-full-pipeline, and the full system — this project beats both naive baselines
on quality while running a fraction of the always-full-pipeline's latency. If asked
"how do you know the personalization/routing actually help," this panel and
`eval/RESULTS.md` / `REPORT.md` are the answer — every number on screen came from a
script in `eval/`, not a slide.

## If something goes wrong

- **First deep query takes 20+ seconds and looks stuck**: that's model cold-start,
  not a hang. Mention it, or run one warm-up query before presenting (see Setup).
- **No LLM explanations, just short template strings**: no `GEMINI_API_KEY` set —
  say so, it's a documented fallback, not a bug.
- **Baseline comparison panel says "not available yet"**: `eval/results/` wasn't
  generated — run `python eval/baseline_comparison.py` once beforehand.
