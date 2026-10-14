# Model configuration

`models.toml` names model profiles and assigns them to `answer`, `supervisor`,
`extraction`, and `summary` roles. The UI selection overrides the model for a
single run; it does not change the embedding model or other conversations.
With no override, each role uses its configured profile. The current rolling
conversation digest is deterministic and does not call the summary model.

Profiles specify provider, model/deployment ID, context window, output reserve,
structured-output support, streaming, and whether temperature is accepted.
These are explicit conservative deployment settings, not automatic discovery of
a model's capabilities. Set verified limits for your deployed model. A smaller
context window trades retrieval depth for lower resource usage.

The bundled model identifiers are examples, not a claim that they are the newest
or best available models. Replace them with a model supported by your account.
Azure requires the **deployment name**, endpoint, API version and credentials.
Set credentials only on the server using the `PARASITE_*` names in `.env.example`.

## Compatibility behavior

- OpenAI/Azure use SDK-validated structured responses. Anthropic uses a forced
  tool response validated against the same Pydantic schema.
- Unsupported structured-output profiles fail explicitly, without parsing
  arbitrary prose as trusted state transitions.
- Output parameters and temperature follow profile capabilities. Responses,
  refusals, truncation and malformed results are checked at the adapter boundary.
- Transient errors have bounded retries; a stream that already emitted text is
  not transparently replayed. The harness reserves the worst-case retry budget.
- Context accounting uses a conservative UTF-8 byte upper bound including schema,
  message framing and output reserve. It favors safety over using every available
  token; it is not a precise model-specific billing estimate.
- Every run records usage and bounded execution events, not private reasoning.

Provider transport tests run without network credentials. They establish adapter
contract compatibility, not live account availability or model quality.

## Independent embeddings

The demo uses deterministic 64-dimensional token hashes (`demo:hash-v1`). This is
a reproducible demonstration, not a competitive semantic embedding model. For
live retrieval select `openai` or `azure`, an embedding model and matching
dimensions in `.env`. Chat can use Anthropic while embeddings use another provider.

Memory stores persist the embedding provider/model identity and dimensions. They
reject incompatible changes, even if dimensions happen to match. Re-embed into a
new store and verify retrieval before switching `PARASITE_DATA_DIR`/Neo4j database;
never mix vectors from different embedding spaces. Retain a private backup of the
previous store for rollback. Historical thesis databases use a different schema;
do not point the new application at them expecting automatic migration.

For the current SQLite schema, stop the server, configure the desired embedding
model, then run:

```powershell
uv run data-parasite reindex --source .local/data --target .local/data-reindexed
```

This preserves record IDs, temporal links and completed conversation history,
leaves the source intact and rejects an existing target. Interrupted runs must be
finished or deleted first. An incomplete reindex target cannot be served. Verify
the target before changing `PARASITE_DATA_DIR`. Neo4j requires an explicit export
and rebuild in a separate database.

## Runtime limits

Use `PARASITE_MAX_STEPS`, `PARASITE_MAX_RUN_TOKENS`, and
`PARASITE_MAX_RUN_SECONDS`. Steps and conservative token reservations persist
across resumes, together with active execution time, so resume cannot evade the budget. Increase a reached limit
explicitly in configuration and restart before resuming that run. Oversized
mandatory user input fails clearly; optional evidence/history is packed within
the remaining context. Credentials and raw upstream error bodies are never sent
to the browser.

An interrupted run can resume using the model currently selected in the UI. Saved
node results are retained; pending model calls use the selected profile. This lets
a larger compatible model handle an input that exceeded a smaller model's context.
