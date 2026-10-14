"""Loopback-only single-user service with persisted, replayable run events."""

import asyncio
import hashlib
import json
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .harness import Harness, HarnessLimits
from .memory import MemoryError, MemoryRecord, Neo4jMemoryStore, SQLiteMemoryStore
from .persistence import RunStore
from .providers import ModelRouter, ProviderError
from .runtime import instance_lock


class NewRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=24000)
    model_profile: str | None = None


class NewSession(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class ResumeRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_profile: str | None = None


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=100000)


def fail(status, code, message):
    raise HTTPException(status, {"code": code, "message": message})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    tasks: dict[str, asyncio.Task] = {}
    cancellations: dict[str, asyncio.Event] = {}
    sessions_busy: dict[str, str] = {}

    async def stop_tasks():
        for event in cancellations.values():
            event.set()
        running = list(tasks.values())
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            stack.enter_context(instance_lock(settings.data_dir))
            migration = settings.data_dir / "reindex.json"
            if (
                migration.exists()
                and json.loads(migration.read_text(encoding="utf-8")).get("status") != "complete"
            ):
                raise ValueError("Reindexing is incomplete; use the previous data directory")
            router = ModelRouter(settings)
            stack.push_async_callback(router.close)
            store = RunStore(settings.data_dir / "sessions.sqlite")
            identity = f"{settings.embedding_provider}:{settings.embedding_model}"
            if settings.memory_backend == "neo4j":
                if not settings.neo4j_password:
                    raise ValueError("Neo4j password must be configured")
                memory = Neo4jMemoryStore(
                    settings.neo4j_uri,
                    settings.neo4j_user,
                    settings.neo4j_password.get_secret_value(),
                    database=settings.neo4j_database,
                    embedding_model=identity,
                    embedding_dimensions=settings.embedding_dimensions,
                )
                stack.push_async_callback(memory.close)
                await memory.initialize()
            else:
                memory = SQLiteMemoryStore(
                    settings.data_dir / "memories.sqlite",
                    embedding_model=identity,
                    embedding_dimensions=settings.embedding_dimensions,
                )
            store.recover_interrupted()
            app.state.store, app.state.router, app.state.memory = store, router, memory
            app.state.harness = Harness(
                router,
                memory,
                store,
                limits=HarnessLimits(
                    max_steps=settings.max_steps,
                    max_total_tokens=settings.max_run_tokens,
                    max_seconds=settings.max_run_seconds,
                    max_retries=0,
                ),
            )
            stack.push_async_callback(stop_tasks)
            yield

    @contextmanager
    def mutation(session_id):
        if session_id in sessions_busy:
            fail(
                409,
                "session_busy",
                "Wait for the active operation before changing this conversation",
            )
        sessions_busy[session_id] = "mutation"
        try:
            yield
        finally:
            sessions_busy.pop(session_id, None)

    app = FastAPI(title="Cognitive Parasite", version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        allowed = {"localhost", "127.0.0.1", "::1"}
        host = urlsplit("http://" + request.headers.get("host", "")).hostname
        if host not in allowed:
            return JSONResponse(
                {
                    "error": {
                        "code": "invalid_host",
                        "message": "This service accepts loopback hosts only",
                    }
                },
                status_code=400,
            )
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and urlsplit(origin).hostname not in allowed
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "invalid_origin",
                        "message": "Cross-site writes are not allowed",
                    }
                },
                status_code=403,
            )
        if int(request.headers.get("content-length", "0")) > 500000:
            return JSONResponse(
                {"error": {"code": "too_large", "message": "Request is too large"}}, status_code=413
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_, exc):
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"code": "request_error", "message": str(exc.detail)}
        )
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Request fields are missing or invalid",
                }
            },
            status_code=422,
        )

    @app.exception_handler(MemoryError)
    async def memory_error(_, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "memory_unavailable",
                    "message": "Memory operation failed; check storage configuration",
                }
            },
            status_code=503,
        )

    @app.exception_handler(ProviderError)
    async def provider_error(_, exc):
        return JSONResponse(
            {"error": {"code": "provider_error", "message": str(exc)}}, status_code=422
        )

    def session_or_404(session_id):
        session = app.state.store.get_session(session_id)
        if not session:
            fail(404, "not_found", "Conversation not found")
        return session

    def run_or_404(run_id):
        run = app.state.store.find_run(run_id)
        if not run:
            fail(404, "not_found", "Run not found")
        return run

    async def execute(session_id, run_id, message=None, profile=None, resume=False):
        try:
            if resume:
                await app.state.harness.resume(
                    session_id, run_id, model_profile=profile, cancel_event=cancellations[run_id]
                )
            else:
                await app.state.harness.run(
                    session_id,
                    message,
                    model_profile=profile,
                    run_id=run_id,
                    cancel_event=cancellations[run_id],
                )
        except asyncio.CancelledError:
            # Covers cancellation before the harness enters its cancellation scope.
            if app.state.store.get_run(session_id, run_id):
                app.state.store.finish_run(session_id, run_id, status="cancelled")
                app.state.store.append_event(
                    session_id, run_id, {"type": "done", "status": "cancelled"}
                )
        except Exception:
            if app.state.store.get_run(session_id, run_id):
                app.state.store.finish_run(
                    session_id,
                    run_id,
                    status="failed",
                    error={"code": "run_failed", "message": "Run failed"},
                )
                app.state.store.append_event(
                    session_id,
                    run_id,
                    {"type": "error", "message": "Run failed; inspect local configuration"},
                )
                app.state.store.append_event(
                    session_id, run_id, {"type": "done", "status": "failed"}
                )
        finally:
            sessions_busy.pop(session_id, None)
            tasks.pop(run_id, None)
            cancellations.pop(run_id, None)

    async def launch(session_id, run_id, **kwargs):
        if session_id in sessions_busy:
            fail(409, "session_busy", "A run is already active for this conversation")
        sessions_busy[session_id] = run_id
        cancellations[run_id] = asyncio.Event()
        tasks[run_id] = asyncio.create_task(execute(session_id, run_id, **kwargs))
        # The journal claim is synchronous and occurs before the first model await.
        await asyncio.sleep(0)
        return {"id": run_id, "status": "running"}

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "mode": "demo" if app.state.router.profile().provider == "demo" else "live",
        }

    @app.get("/api/models")
    async def models():
        return {
            "models": [
                {
                    "id": p.id,
                    "label": p.label or p.model,
                    "provider": p.provider,
                    "available": app.state.router.available(p),
                    "reason": None
                    if app.state.router.available(p)
                    else "Server credentials required",
                }
                for p in app.state.router.profiles.values()
            ],
            "default": app.state.router.roles["answer"],
        }

    @app.get("/api/sessions")
    async def sessions(limit: int = Query(100, ge=1, le=1000)):
        return {"sessions": app.state.store.list_sessions(limit)}

    @app.post("/api/sessions", status_code=201)
    async def create_session(body: NewSession):
        return app.state.store.create_session(title=body.title)

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        session = session_or_404(session_id)
        return {
            **session,
            "messages": app.state.store.history(session_id, limit=1000),
            "runs": list(reversed(app.state.store.list_runs(session_id))),
        }

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        session_or_404(session_id)
        with mutation(session_id):
            await app.state.memory.delete_session(session_id)
            await app.state.store.delete_session(session_id)

    @app.get("/api/sessions/{session_id}/memories")
    async def memories(session_id: str, limit: int = Query(100, ge=1, le=1000)):
        session_or_404(session_id)
        records = await app.state.memory.list(session_id, limit=limit)
        return {"memories": [{**record.model_dump(), "text": record.content} for record in records]}

    @app.delete("/api/sessions/{session_id}/memories/{memory_id}", status_code=204)
    async def delete_memory(session_id: str, memory_id: str):
        session_or_404(session_id)
        with mutation(session_id):
            if not await app.state.memory.delete(session_id, memory_id):
                fail(404, "not_found", "Memory not found")

    @app.post("/api/sessions/{session_id}/runs", status_code=202)
    async def create_run(session_id: str, body: NewRun):
        session = session_or_404(session_id)
        if not body.message.strip():
            fail(422, "empty_message", "Enter a message")
        try:
            profile = app.state.router.profile("answer", body.model_profile)
            if not app.state.router.available(profile):
                raise ProviderError("Credentials are missing for the selected provider")
        except ProviderError as exc:
            fail(422, "invalid_model", str(exc))
        if session["title"] == "New conversation":
            app.state.store.set_title(session_id, " ".join(body.message.split())[:70])
        return await launch(
            session_id, str(uuid4()), message=body.message, profile=body.model_profile
        )

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        run = run_or_404(run_id)
        if run_id in cancellations:
            cancellations[run_id].set()
        return {"id": run_id, "status": "cancelling" if run_id in tasks else run["status"]}

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    async def resume(run_id: str, body: ResumeRun | None = None):
        run = run_or_404(run_id)
        if run["status"] not in {"cancelled", "limited", "failed"}:
            fail(409, "not_resumable", "Only interrupted runs can be resumed")
        profile = body.model_profile if body else None
        selected = app.state.router.profile("answer", profile or run["model_profile"])
        if not app.state.router.available(selected):
            fail(422, "invalid_model", "Credentials are missing for the selected provider")
        cursor = app.state.store.event_cursor(run["session_id"], run_id)
        result = await launch(run["session_id"], run_id, resume=True, profile=profile)
        return {**result, "event_cursor": cursor}

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = Query(0, ge=0)):
        run = run_or_404(run_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            fail(422, "invalid_cursor", "Event cursor must be an integer")
        # Reconnection replays the current attempt, never an earlier terminal event.
        attempt = app.state.store.event_cursor(run["session_id"], run_id, attempt=True)
        cursor = max(cursor, attempt - 1)

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                batch = app.state.store.events(run["session_id"], run_id, after=cursor)
                for event in batch:
                    cursor = event["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event["type"] == "done":
                        return
                current = app.state.store.get_run(run["session_id"], run_id)
                if (
                    current
                    and current["status"] in {"completed", "failed", "cancelled", "limited"}
                    and not batch
                ):
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.15)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.post("/api/documents", status_code=201)
    async def ingest(body: Document):
        session_or_404(body.session_id)
        if not body.text.strip():
            fail(422, "empty_document", "Document text is empty")
        with mutation(body.session_id):
            document_id = hashlib.sha256(
                (body.session_id + "\0" + body.title + "\0" + body.text).encode()
            ).hexdigest()
            # Character cap chosen to fit embedding limits even for four-byte Unicode.
            chunks = [body.text[start : start + 3000] for start in range(0, len(body.text), 2800)]
            embeddings = await app.state.router.embed(chunks)
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                record = MemoryRecord(
                    id=f"{document_id}:{index}",
                    kind="semantic",
                    content=chunk,
                    source=f"document:{document_id}",
                    document=body.title,
                    chunk_order=index,
                    embedding=embedding,
                    embedding_model=f"{settings.embedding_provider}:{settings.embedding_model}",
                )
                await app.state.memory.upsert(body.session_id, record)
            return {"id": document_id, "chunks": len(chunks)}

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app
