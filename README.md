# LLM Chatbot with Key Failover and Response Caching

React + FastAPI + SQLite + LiteLLM (Gemini). Multi-turn chat that survives failing API keys and caches repeated prompts.

## 1. Live URLs
- Frontend: https://llm-chatbot-wheat.vercel.app
- Backend: https://suryansh-llm-chatbot-api.fly.dev

## 2. Run locally

### With Docker
```bash
cp .env.example .env      # put 2+ Gemini keys in LLM_API_KEYS
make up                   # frontend :3000, backend :8000
make down
```
### Without Docker
```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2 DATABASE_URL=sqlite:///./app.db ALLOWED_ORIGINS=http://localhost:3000 ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:build_app --factory --port 8000
# tests (no API keys needed; LiteLLM mock responses)
python -m pytest
# frontend
cd frontend && npm install && npm run dev      # http://localhost:3000
```
Variables are listed in `.env.example`. `VITE_API_BASE_URL` is baked in at build time.

## 3. Design decisions
**Key fallback.** `LLMGateway` walks the key pool in order (`key_1`, `key_2`, …) and calls `litellm.acompletion` with each key. Any failure (429, quota, 5xx, timeout, auth) moves to the next key. I chose an explicit loop over `litellm.Router` because the API must report exactly which key answered (`key_id`) and how many failed first (`fallback_attempts`), and the failure-simulation hook is trivial to inject per request. If every key fails the API returns `503 {"detail":"all providers unavailable"}` and nothing is saved. Keys are never returned or logged; only ids are.

**Caching.** LiteLLM's own `Cache(type="local")` (in-memory). I call its `async_get_cache` / `async_add_cache` directly with `model + full message list` as the key, because LiteLLM's automatic key also hashes the `api_key`, which would make the same prompt miss after failover to another key. The cached value stores reply and token usage, so hits return identical text and the original token counts with `key_id=null`. Requests carrying `X-Simulate-Failure` bypass the cache (otherwise a cached prompt would never exercise failover). Trade-off: the current LiteLLM release removed its disk backend, so the cache is cleared on restart; chat history is not.

**SQLite sessions.** Stdlib `sqlite3`, WAL mode, schema created on startup at `DATABASE_URL` (a Docker volume at `/data`). `messages` follows the required schema; a small `sessions` table stores the per-session system prompt, so it never appears in history. A user+assistant pair is written in one transaction only after the LLM succeeded, so 422/503 requests leave no trace. Blocking DB calls run via `asyncio.to_thread`.

**Other:** every error is JSON (`detail`), including a catch-all handler (no stack traces); CORS limited to `ALLOWED_ORIGINS`; non-root container user; multi-stage Dockerfiles.

## 4. Verification
```bash
B=http://localhost:8000
curl $B/health
# live, then cache (same message, NEW session)
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a","message":"What is the capital of France?"}'
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"b","message":"What is the capital of France?"}'   # LLM_CACHE, key_id null
# failover
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"c","message":"hi"}'    # key_id key_2, fallback_attempts 1
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"d","message":"hi"}'      # 503
curl -s $B/sessions/a/messages    # history with per-message token metadata
curl -s $B/sessions/d/messages    # 404: failed request was not stored
```
In the UI, each reply shows source, model, latency and that request's input/output tokens. Open "Session settings" to type a failover header (e.g. `key_1=429`) and see `key_2` answer. 15 backend tests cover validation, cache, failover, 503, history and CORS (`make test`).

## 5. Setup Used
- Editor / AI tools: `TODO – e.g. VS Code + Claude`

## 6. Bonus features
- Optional per-session system prompt field (`system-prompt-input`).
- UI shows `key_id` and fallback count next to each reply; failover header field for demos.
- Health check in the backend image; `fly.toml` for deployment with a persistent volume.
