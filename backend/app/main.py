import asyncio
import logging
import time
from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, load_settings
from .db import Database
from .gateway import AllProvidersUnavailable, LLMGateway, parse_simulation
from .schemas import ChatRequest, ChatResponse, Metadata

log = logging.getLogger("app")


def create_app(settings: Optional[Settings] = None, gateway: Optional[LLMGateway] = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.db_path)
    db.init()
    gw = gateway or LLMGateway(settings.api_keys, settings.model)

    app = FastAPI(title="LLM Chatbot", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.allowed_origins,
        allow_methods=["*"], allow_headers=["*"],
    )

    # ---- error handlers: always JSON {"detail": ...}, never HTML or a stack trace
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errs})

    @app.exception_handler(AllProvidersUnavailable)
    async def _unavailable(_: Request, __: AllProvidersUnavailable):
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    # ---- routes
    @app.get("/health")
    async def health():
        await asyncio.to_thread(db.ping)
        return {"status": "ok", "keys_configured": len(gw.keys), "cache_enabled": gw.cache_enabled}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
        start = time.perf_counter()
        sid = body.session_id

        stored_prompt = await asyncio.to_thread(db.get_system_prompt, sid)
        system_prompt = body.system_prompt or stored_prompt or settings.default_system_prompt
        history = await asyncio.to_thread(db.get_history, sid)

        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": body.message})

        simulate = {}
        if settings.enable_failure_simulation:
            simulate = parse_simulation(x_simulate_failure, list(gw.keys))

        result = await gw.complete(messages, simulate)  # raises AllProvidersUnavailable -> 503

        latency_ms = max(0, int(round((time.perf_counter() - start) * 1000)))
        meta = Metadata(
            resolution_source=result.resolution_source, model=result.model,
            latency_ms=latency_ms, input_tokens=result.input_tokens,
            output_tokens=result.output_tokens, key_id=result.key_id,
            fallback_attempts=result.fallback_attempts,
        )
        # Persist only after success, so 422/503 never reach history.
        await asyncio.to_thread(
            db.save_exchange, sid, body.message, result.reply, meta.model_dump(),
            body.system_prompt,
        )
        return ChatResponse(session_id=sid, reply=result.reply, metadata=meta)

    @app.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str):
        if not await asyncio.to_thread(db.session_exists, session_id):
            return JSONResponse(status_code=404, content={"detail": "session not found"})
        history = await asyncio.to_thread(db.get_history, session_id)
        return {"session_id": session_id, "messages": history}

    return app


def build_app() -> FastAPI:
    """Entry point for uvicorn: `uvicorn app.main:build_app --factory`."""
    logging.basicConfig(level=logging.INFO)
    return create_app()
