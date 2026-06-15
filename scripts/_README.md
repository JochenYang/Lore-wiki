# scripts/ — operator & benchmark scripts

Hand-run scripts. **Not** part of the test suite (the pytest tests
under `../tests/` are what CI runs).

## Operator scripts

- The release pipeline is fully driven by the `Publish to PyPI`
  GitHub Actions workflow (`.github/workflows/publish.yml`).
  Maintainers bump the version, commit, tag, and push; the workflow
  handles tests, lint, build, and PyPI upload via Trusted
  Publishing (OIDC). See [the install doc](../docs/install.md) for
  the full checklist.
- `install.py` lives in `../skills/`, not here.

## Benchmark / smoke scripts (dev only)

- `smoke_db.py` / `smoke_index.py` / `smoke_bm25.py` — quick
  end-to-end probes for the FTS5 + indexer + BM25 stack.
- `compare_tokenizers.py` / `debug_rank.py` — diagnostic
  helpers for FTS5 tokenizer choice and rank-row inspection.
- `recall_phase1.py` / `recall_phase2.py` — recall measurements
  used during retrieval tuning.

These are intentionally *not* wired into CI: they depend on a
live `~/.lorewiki/` state, take a long time to run, and exist
to support manual iteration while developing the indexer.
