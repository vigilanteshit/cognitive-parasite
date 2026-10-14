# The Data Parasite

The Data Parasite is a research prototype for language agents with long-term memory. It combines a Python service using LangGraph, a FastAPI API, and a React and TypeScript web client. Durable local memory uses SQLite by default; Neo4j is an optional backend for semantic and episodic memory. Episodic records preserve events over time, and temporal updates let newer information supersede earlier facts.

The supervisor chooses between direct answers, semantic document retrieval and
episodic experience retrieval. The learning pipeline retains subjective
importance, five memory categories, career state/action pairs and versioned
updates from the original master's thesis. Context, steps, tokens and active run
time are bounded; checkpoints support cancellation and resume. Model profiles
can be switched independently of the embedding model.

## Run locally

Clone the public repository and install the Python package:

```powershell
git clone https://github.com/vigilanteshit/cognitive-parasite.git
cd cognitive-parasite
uv sync --locked
```

Install and build the frontend before starting the API, so FastAPI can serve the built client:

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
```

The default profile is a deterministic local demo and does not require an external language-model account. Start the API from the repository root:

```powershell
uv run data-parasite serve --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. For frontend development, run `npm --prefix frontend run dev`.

Optional provider profiles can connect to Azure OpenAI, OpenAI, or Anthropic. Configure credentials through environment variables or a local, untracked environment file; never commit credentials.

See [model configuration](docs/models.md) for role assignments, compatibility,
embedding reindexing and runtime limits. The demo recognizes explicit statements
such as `I prefer green tea.` and can retrieve ingested text. Live model reasoning
requires a configured provider. This is a local, single-user application.

## Project layout

- `src/data_parasite/` — Python package, agent workflows, memory services, and API.
- `frontend/` — React and TypeScript client.
- `docs/` — [model configuration](docs/models.md), [core behavior and preservation](docs/core-preservation.md), research context, and publication guidance.
- `scripts/audit_publication.py` — safe source and history audit for public releases.
- `scripts/evaluate.py` — deterministic synthetic retrieval regression; it does not call external APIs.

The thesis was inspired by:

- [GraphRAG: From Local to Global](https://arxiv.org/abs/2404.16130) — graph-backed retrieval and connected knowledge.
- [Cognitive Architectures for Language Agents (CoALA)](https://arxiv.org/abs/2309.02427) — modular memory, actions and decision-making.
- [Generative Agents](https://arxiv.org/abs/2304.03442) — experience storage and retrieval over time.

These are inspirations, not claims of reproducing the papers' complete systems.
[Research and design](docs/research.md) explains the connection and discusses
related MemGPT and A-MEM work.

## Verify

```powershell
uv run pytest
uv run python scripts/evaluate.py
npm --prefix frontend test
```

The evaluation uses synthetic retrieval cases and a naive lexical comparison.
It does not establish state-of-the-art answer quality. Provider contracts are
tested offline; CI also checks a real disposable Neo4j service and browser flows.
Paid-model quality, cost and account compatibility require separate evaluation
with newly configured credentials.

## Citation and license

If you use this work, cite it using [CITATION.cff](CITATION.cff). This project is distributed under the MIT License; see [LICENSE](LICENSE).
