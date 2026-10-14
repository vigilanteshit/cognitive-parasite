# Modernization scope

The original thesis repository remains the private research archive. The public
release is an independently rooted Git history, licensed MIT by its author.
No original environment files, datasets, papers, logs, or notebook outputs are
eligible for publication. Existing uncommitted changes remain in the original
working directory.

## Ordered acceptance checkpoints

1. **Baseline and preservation:** document the original supervisor, semantic and
   episodic retrieval, categorization, importance, state/action associations,
   temporal memory updates. Test these behaviors using synthetic fixtures.
2. **Portable runtime:** installable Python package, validated role-based model
   profiles, Azure/OpenAI and Anthropic adapters, separate embedding identity.
   Verify provider contracts with isolated transports before any paid live run.
3. **Bounded harness:** per-call context budgets, per-run steps/tokens/deadline,
   duplicate-action detection, cancellation, durable checkpoints and idempotent
   writes. Verify long context, loops, resumed runs and session isolation.
4. **Usable application:** FastAPI + React streaming workbench, sessions, model
   selection, source/memory inspection, document ingestion, stop/resume. Verify
   both API boundaries and browser interactions.
5. **Reproducibility:** locked dependencies, CI, offline demo and evaluation
   fixtures. Measure retrieval/grounding and execution budgets, separating demo
   tests from any live-model performance claims.
6. **Publication:** README, research citations, license and citation metadata;
   redacted secret/content audit of the exact public tree and its entire history.
   Publish only the verified clean main branch to the separate public repository.

## Constraints

Single-user local application, bound to loopback by default. Multi-user internet
hosting needs a separate authentication and ownership design. No real thesis
credentials are used in tests. SDK request retries are bounded and no streamed
answer is transparently replayed after output has reached the client.
