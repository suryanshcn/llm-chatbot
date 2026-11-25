"""LLM gateway: ordered key pool with failover + LiteLLM response cache.

Why an explicit loop instead of litellm.Router: we must report exactly which key
answered (key_id) and how many failed first (fallback_attempts), and honour the
X-Simulate-Failure hook per request. LiteLLM still performs every provider call
(litellm.acompletion) and provides the cache (litellm.caching.Cache).

Why the cache is called directly: LiteLLM's automatic cache key also hashes the
api_key, so the same prompt answered via key_2 would miss. The contract says the
key is model + full message list, so we build the lookup from exactly those."""
import logging
import time
from dataclasses import dataclass
from typing import Optional

import litellm
from litellm.caching.caching import Cache

log = logging.getLogger("gateway")
SIM_STATUSES = {429, 500, 502, 503}


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    resolution_source: str
    key_id: Optional[str]
    fallback_attempts: int


def parse_simulation(header: Optional[str], key_ids: list[str]) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {key_id: status}. Bad pairs are ignored."""
    out: dict[str, int] = {}
    if not header:
        return out
    for pair in header.split(","):
        name, sep, status = pair.strip().partition("=")
        name, status = name.strip(), status.strip()
        if not sep or not status.isdigit() or int(status) not in SIM_STATUSES:
            continue
        if name == "*":
            out.update({k: int(status) for k in key_ids})
        elif name in key_ids:
            out[name] = int(status)
    return out


class SimulatedProviderError(Exception):
    def __init__(self, status: int):
        super().__init__(f"simulated provider status {status}")
        self.status = status


class LLMGateway:
    def __init__(self, api_keys: list[str], model: str, extra_kwargs: Optional[dict] = None):
        self.keys = {f"key_{i}": k for i, k in enumerate(api_keys, start=1)}
        self.model = model
        self.extra = extra_kwargs or {}  # tests pass mock_response here
        self.cache = Cache(type="local")  # LiteLLM in-memory cache
        litellm.drop_params = True

    @property
    def cache_enabled(self) -> bool:
        return self.cache is not None

    async def complete(self, messages: list[dict], simulate: Optional[dict[str, int]] = None) -> LLMResult:
        simulate = simulate or {}
        # Simulation must exercise failover, so it never reads from (or writes to) the cache.
        use_cache = not simulate

        if use_cache:
            hit = await self.cache.async_get_cache(model=self.model, messages=messages)
            if hit:
                return LLMResult(hit["reply"], hit["model"], hit["input_tokens"],
                                 hit["output_tokens"], "LLM_CACHE", None, 0)

        failures = 0
        for key_id, key in self.keys.items():
            try:
                if key_id in simulate:
                    raise SimulatedProviderError(simulate[key_id])
                resp = await litellm.acompletion(
                    model=self.model, messages=messages, api_key=key,
                    caching=False, num_retries=0, timeout=45, **self.extra,
                )
                reply = (resp.choices[0].message.content or "").strip()
                if not reply:
                    raise ValueError("empty completion")
                usage = resp.usage
                result = LLMResult(reply, self.model, int(usage.prompt_tokens),
                                   int(usage.completion_tokens), "LIVE_INFERENCE", key_id, failures)
                if use_cache:
                    await self.cache.async_add_cache(
                        {"reply": reply, "model": self.model,
                         "input_tokens": result.input_tokens,
                         "output_tokens": result.output_tokens},
                        model=self.model, messages=messages)
                return result
            except Exception as e:  # 429 / quota / 5xx / auth / timeout -> next key
                failures += 1
                log.warning("%s failed (%s: %s); trying next key", key_id, type(e).__name__, str(e)[:120])
        raise AllProvidersUnavailable()
