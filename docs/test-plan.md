
LoreWiki end-to-end test plan
=============================

Scenario 1 — pure CLI (no LLM), 5 min, no external deps.
Verify: indexer, BM25 + hierarchy + RRF, topic flow.

Step 1 — prepare the example wiki
    rm -rf /tmp/lw-test
    cp -r D:/codes/Lorewiki/example_wiki /tmp/lw-test
    cd /tmp/lw-test && ls *.md
    # expect: index.md, api/order/checkout.md, api/user/auth.md,
    #         patterns/rate-limit.md, patterns/retry.md

Step 2 — end-to-end CLI smoke
    lorewiki --version                                # -> LoreWiki 0.1.0
    lorewiki index --path /tmp/lw-test                # -> chunks=40, nodes=10
    lorewiki search "JWT" --path /tmp/lw-test --mode mix --top-k 3 --raw
                                                    # -> JSON array, retriever=mix
    lorewiki search "限流" --path /tmp/lw-test --mode mix --top-k 3 --raw
                                                    # -> tests CJK recall
    lorewiki ask "how does rate limiting work?" --path /tmp/lw-test --raw
                                                    # -> used_llm=false,
                                                    #    degraded_reason="llm_unavailable"
                                                    #    answer = top-K panel

Step 3 — second-brain / topic flow
    lorewiki topic create react --source /tmp/lw-test
    lorewiki topic use react
    lorewiki index
    lorewiki search "JWT" --raw                       # goes to react topic db
    lorewiki topic show
    lorewiki topic list --raw
    lorewiki topic rename react frontend-react        # current pointer updated
    lorewiki topic list --raw
    lorewiki topic delete react --force

---

Scenario 2 — local LLM via Ollama (needs `ollama` installed)

    ollama pull qwen2.5:7b
    cat > ~/.lorewiki/config.toml << EOF
    [llm]
    enabled = true
    backend = "ollama"
    ollama_model = "qwen2.5:7b"
    EOF
    lorewiki --topic react ask "JWT 鉴权流程怎么走？" --top-k 5 --raw
                                                    # -> used_llm=true,
                                                    #    answer from real LLM

---

Scenario 3 — remote OpenAI-compatible (OpenRouter / self-hosted vLLM)

    export LOREWIKI_LLM__ENABLED=true
    export LOREWIKI_LLM__BACKEND=openai
    export LOREWIKI_LLM__OPENAI_API_KEY=sk-or-...
    export LOREWIKI_LLM__OPENAI_BASE_URL=https://openrouter.ai/api/v1
    export LOREWIKI_LLM__OPENAI_MODEL=meta-llama/llama-3.1-8b-instruct:free
    lorewiki ask "react hooks closure" --top-k 5 --raw

What is NOT supported today (documented but not implemented)
------------------------------------------------------------

Azure OpenAI:
    Azure endpoint template is
    https://{r}.openai.azure.com/openai/deployments/{d}/chat/completions?api-version=...
    LoreWiki's OpenAIClient hard-codes the path to f"{base_url}/chat/completions"
    so the api-version query param gets truncated.

    Workaround today: pin to a custom reverse proxy that strips the
    api-version param. Or wait for the phase-7 Azure support (or open
    an issue if you need it sooner).

Other gaps (see docs/production-readiness.md):
    - Vector retrieval  (planned, not yet implemented)
    - lorewiki update --watch  (file-watcher placeholder)
    - /ask/stream SSE  (no streaming yet)
