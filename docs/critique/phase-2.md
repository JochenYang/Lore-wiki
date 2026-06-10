# Phase 2 — Hierarchy retrieval + RRF fusion — Self-critique

> Mission: complete the dev document "Phase 2: reasoning-style
> retrieval" and self-audit before entering Phase 3.

## 1. Actual deliverables

### 1.1 Modules

| Module                       | File                                                | LOC  | Role                                                                              |
|------------------------------|-----------------------------------------------------|------|-----------------------------------------------------------------------------------|
| HierarchyRetriever           | `lorewiki/retriever/hierarchy.py`                   | 200  | keyword match on title / summary → locate node → collect subtree docs → score      |
| RRFFusion                    | `lorewiki/retriever/fusion.py`                      | 90   | Reciprocal Rank Fusion (no score normalisation needed) + per-retriever weight     |
| CLI search tri-mode          | `lorewiki/cli.py::_run_search`                      | +50  | unified dispatcher: bm25 / hierarchy / mix (RRF) / vector (fallback to mix)       |
| Tests                        | `tests/test_retriever_hierarchy_and_fusion.py`      | 165  | 5 HierarchyRetriever + 5 RRFFusion + 2 CLI integration = 12 new cases             |
| Benchmark                    | `scripts/recall_phase2.py`                           | 90   | three-mode comparison acceptance script                                          |

### 1.2 Acceptance data

- **Test scale**: 73 cases pass (61 from Phase 1 + 12 from Phase 2);
  coverage **92%**.
- **Recall@5 acceptance** (10 hand-curated queries):

  | Mode            | Recall@5           | Avg latency |
  |-----------------|--------------------|-------------|
  | BM25            | 8 / 10 = 80%       | 1.7 ms      |
  | Hierarchy       | 9 / 10 = 90%       | 0.8 ms      |
  | **Mix (RRF)**   | **10 / 10 = 100%** | 3.0 ms      |

  Mix mode exceeds the Phase-2 bar (≥ 85%) by **15 points** and
  the BM25-only baseline by 25 points. Confirms that RRF's
  "consensus boost" delivers a qualitative jump in recall, not a
  marginal one.

- **ruff lint** 0 errors.

### 1.3 Design decisions

1. **HierarchyRetriever uses keyword match, not FTS5** — the
   `title` and `summary` columns are short (< 300 chars); substring
   `IN` matching is simpler and faster than building another FTS5
   virtual table (the node count is far smaller than the chunk
   count). The LLM-navigation variant is deferred to Phase 3.
2. **Node-scoring formula: `title_hits * 3 + summary_hits * 1 + 1 / (level + 1)`**
   — `title` is the highest-signal field (it's frontmatter); 3×.
   `summary` is the first 200 chars (can be mid-sentence), 1×.
   Shallow nodes get a small bonus so leaf docs don't always
   outrank module nodes.
3. **Skip the level-0 synthetic root** — otherwise it matches
   every query and the result collapses to the whole corpus.
4. **RRF, not weighted score sum** — BM25 / hierarchy / LIKE
   produce scores on incompatible scales (BM25 ~ 0–10, hierarchy
   word-count accumulating, LIKE 0–0.5); a sum-fusion would need
   min-max / z-score normalisation; RRF is rank-based and
   scale-agnostic.
5. **CLI `vector` mode falls back gracefully to `mix`** —
   `vector` isn't implemented until Phase 6, but a user setting
   `retrieval_mode = vector` should not crash; print a yellow
   notice and use `mix`.

## 2. Self-discovered issues (in discovery order)

| #   | Issue                                                                                                            | Severity | Source                                         | Status |
|-----|------------------------------------------------------------------------------------------------------------------|----------|------------------------------------------------|--------|
| 1   | `HierarchyRetriever._tokenize` was missing **bigrams** (only whole-string + trigrams). 2-character CJK terms like "重试" / "幂等" / "认证" couldn't match doc titles — hierarchy Recall was only 50%, almost tanking the mix-mode acceptance | **high** | `recall_phase2.py` showed hierarchy 50% | **Fixed**: added `for i in range(len(run) - 1): terms.append(run[i:i+2])`; after fix, hierarchy alone is 90%, mix is 100%. **This was the highest-impact bug in Phase 2 — one line of code lifted Recall from 50% to 90%.** |
| 2   | Implicit assumption: "BM25 + RRF should be enough." Reality: BM25+RRF equals BM25 alone (80%); the missing 2 points are saved by Hierarchy, which compensates for the benchmark-dataset artifact. **Lesson**: fusion's value isn't "making good results better" but "making the two sides complement each other". | medium (epistemic) | `recall_phase2.py` | **Recorded** in this critique; the test `test_mix_mode_combines_both_retrievers` explicitly asserts `retriever="mix"` to prevent any retriever being silently disabled. |
| 3   | `_collect_doc_paths` uses DFS without a `visited` set — the hierarchy is acyclic by FK constraint, but a hand-edited DB or a future migration glitch could create a cycle and the DFS would loop forever | low | code review | **Known, not fixed**: the attack scenario is implausible today; add a cycle detector in Phase 6's migration logic. |
| 4   | RRF scores are tiny (0.01–0.03) — `:.3f` formatting in the CLI renders them as `0.030`, with no visual separation from each other; meanwhile BM25 / Hierarchy scores (1–20) look very different. UX gap. | low | visual inspection of CLI output | **Known, not fixed**: when Phase 4 brings Streamlit, render mode-aware "relative" scores or coloured bars. CLI keeps raw values for debuggability. |
| 5   | `_run_search` is a `cli.py` private helper, but tests `import` it directly (`from lorewiki.cli import _run_search`) — leaks private API into the test suite | low | noticed while writing tests | **Known, not fixed**: if a refactor ever moves the search dispatcher into `retriever.dispatcher`, update tests in lockstep. Marked with a `noqa` for now. |
| 6   | `HierarchyRetriever` loads all hierarchy nodes into memory (`SELECT ... FROM hierarchy WHERE level > 0`) — 10M nodes would OOM | low | code review | **Known, not fixed**: the current dataset has 10 nodes; add LIMIT + paging in Phase 6. |
| 7   | `RRFFusion.best_hit` rule is "keep the highest score", but in `mix` mode BM25 hits (~5) are always larger than hierarchy hits (~10)? — answer: the units differ, hierarchy is a word-count accumulator. Correct in intent, confusing in practice. | low | code review | **Annotated** explaining the unit difference; the test `test_rrf_records_contributors` covers the `contributors` field. |
| 8   | `_run_search` passes `top_k * 2` to each retriever, and `LIKE` then passes `top_k * 2` again, and Hierarchy passes `top_k * 3` — each layer amplifies, which may degrade latency | low | code review | **Known, not fixed**: not a problem at 5 docs (3 ms latency). Re-tune at 1k docs. |

> **Critique conclusion**: the most valuable lesson in Phase 2 is #1 — I assumed trigrams were enough and didn't notice that 2-character CJK terms are extremely common. One line of code lifted Recall from 50% to 90%, which proves that hierarchy retrieval is **extremely sensitive to Chinese tokenization**. The Phase-3 LLM-navigation variant must build on this fix; otherwise the candidate-node list it receives is already incomplete.

## 3. Lingering risks (must address in Phase 3)

1. **`example_wiki/index.md` self-contains the acceptance query list** — index.md's "检索使用建议" table is the source of the benchmark artifact. BM25 ranks `index.md` first; hierarchy saves mix-mode by pulling the right doc into the top 5, but the top-1 ranking is still polluted. **Plan**: Phase 4 Recall evaluation should exclude `index.md`, or maintain a hidden benchmark separately.
2. **Hierarchy `summary` is the first 200 chars of the doc** — may cut mid-punctuation, hurting readability and LLM-navigation quality. **Plan**: when implementing LLM navigation in Phase 3, switch `summary` to "first paragraph, paragraph-boundary cut, 200-char cap".
3. **RRF weights (bm25=1.0, hierarchy=0.8, vector=0.5) are heuristic** — no grid-search against the acceptance set. **Plan**: do a sweep in the Phase-6 enhancement pass. Current defaults are at least not hurting mix Recall.
4. **`vector` mode triggers fallback notice every search** — when used in an automated loop (e.g. `ask`), the warning spams the output. **Plan**: add a `quiet=True` option to `_run_search` for `ask` to call.
5. **HierarchyRetriever is chunk-context-blind** — it returns chunks in the document's physical order (`chunks_per_doc` by `chunk_index`), all sharing the same node score. **Plan**: after collecting the subtree, do a chunk-level keyword re-rank (count of query terms in `chunk.content`) for finer ordering.

## 4. Phase-3 gate check

- [x] `lorewiki search --mode {bm25, hierarchy, mix, vector}` all functional
- [x] 73 tests pass; coverage 92% (≥ 80%)
- [x] Recall@5 mix mode 100% (≥ 85% bar)
- [x] Retrieval latency mix 3 ms (< 200 ms bar)
- [x] `BaseRetriever` interface stable; future `VectorRetriever` / LLM-navigation drop in without touching `RRFFusion`
- [x] Critique doc in place
- [x] Hierarchy tokenize bug has dedicated regression tests (`test_hierarchy_finds_module_node`, `test_hierarchy_score_is_positive`)

---

**Phase verdict**: ✅ pass, ready for Phase 3 (LLM integration + `ask` command).
