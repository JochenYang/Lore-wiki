# example_wiki — benchmark & smoke-test fixture

This directory is **not** a starter template. It is a **curated
benchmark fixture** used by the scripts in `../scripts/` to verify
retrieval quality and to smoke-test the indexer end-to-end.

## Why it lives in the repo

- **Recall@5 benchmark** (`../scripts/recall_phase1.py`,
  `../scripts/recall_phase2.py`) — measures how well BM25, the
  hierarchy retriever, and the RRF fusion find the expected chunks
  for a fixed query set. The fixture is curated so the expected
  chunk ids per query are deterministic; regressions in the
  chunker or tokenizer surface immediately.
- **End-to-end smoke** (`../scripts/smoke_index.py`,
  `../scripts/smoke_bm25.py`, `../scripts/smoke_db.py`) — sanity
  checks before a release: "does the indexer still build 40 chunks
  in < 1 s? does the FTS5 query path still return hits?"
- **Debug** (`../scripts/debug_rank.py`) — inspects the chunks
  matched for a single query when something looks off in the
  recall numbers.

## What it contains

```text
example_wiki/
├── index.md               # "table of contents" doc
├── api/
│   ├── order/checkout.md  # full-stack feature doc
│   └── user/auth.md       # auth / token / session notes
└── patterns/
    ├── rate-limit.md      # distributed rate-limiting patterns
    └── retry.md           # retry / idempotency patterns
```

5 markdown files, ~40 chunks after indexing, ~10 hierarchy nodes
(``api/order``, ``api/user``, ``patterns/rate-limit``,
``patterns/retry``, plus the root).

## If you want to use lorewiki for real

**Don't start here.** Create your own vault:

```bash
lorewiki topic create my-project
# drop your markdown into ~/lorewiki/topics/my-project/
lorewiki topic use my-project
lorewiki index
lorewiki search "..."
```

The ``example_wiki/`` fixture is intentionally small, repetitive,
and biased toward Chinese keyword queries — useful for benchmarking,
useless for your day job.

## Re-running the benchmark

```bash
# From the repo root
python scripts/recall_phase1.py          # BM25-only Recall@5
python scripts/recall_phase2.py          # hierarchy + RRF
```

If you delete this directory the scripts will fail with
``FileNotFoundError: .../example_wiki/...`` — that's expected and
means you've lost the recall regression coverage. Re-create the
fixture (it's just 5 markdown files) or replace it with a larger
private benchmark.
