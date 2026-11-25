SIM = "X-Simulate-Failure"


def chat(c, sid="s1", msg="What is the capital of France?", headers=None, **extra):
    return c.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_live_then_cache_across_sessions(client):
    a = chat(client, "s1").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a["metadata"]["key_id"] == "key_1" and a["metadata"]["fallback_attempts"] == 0
    b = chat(client, "s2").json()  # same first message, new session
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"]
    assert b["metadata"]["key_id"] is None and b["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    assert b["metadata"]["output_tokens"] == a["metadata"]["output_tokens"]


def test_different_message_never_cached(client):
    chat(client, "s1", "hello there")
    r = chat(client, "s2", "something else").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_tokens_are_per_request_not_cumulative(client):
    a = chat(client, "s1", "aaaa bbbb").json()["metadata"]["input_tokens"]
    b = chat(client, "s2", "cccc dddd").json()["metadata"]["input_tokens"]
    assert abs(a - b) <= 2
    # a 2nd turn reports that request's own usage, not a running total (mock usage is constant)
    c2 = chat(client, "s1", "eeee ffff").json()["metadata"]
    assert c2["input_tokens"] == a and c2["output_tokens"] == 20


def test_failover_key1_429(client):
    r = chat(client, headers={SIM: "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
    assert m["resolution_source"] == "LIVE_INFERENCE"


def test_failover_bypasses_cache(client):
    chat(client, "s1")  # warm the cache
    r = chat(client, "s2", headers={SIM: "key_1=500"}).json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["metadata"]["key_id"] == "key_2"


def test_all_keys_fail_503_and_history_untouched(client):
    r = chat(client, "s9", headers={SIM: "*=429"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s9/messages").status_code == 404
    r = chat(client, "s9", headers={SIM: "key_1=429,key_2=500"})
    assert r.status_code == 503


def test_simulation_disabled_ignores_header(make_client):
    c = make_client(simulation=False)
    r = chat(c, headers={SIM: "*=429"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_1"


def test_real_provider_error_falls_over(make_client):
    c = make_client(extra={"mock_response": Exception("boom")})
    r = chat(c)
    assert r.status_code == 503 and r.json()["detail"] == "all providers unavailable"


def test_multi_turn_history_and_separate_sessions(client):
    chat(client, "a", "first")
    chat(client, "a", "second")
    chat(client, "b", "other")
    h = client.get("/sessions/a/messages").json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant", "user", "assistant"]
    assert h["messages"][0]["content"] == "first" and "metadata" not in h["messages"][0]
    assert set(h["messages"][1]["metadata"]) >= {"resolution_source", "input_tokens", "output_tokens"}
    assert len(client.get("/sessions/b/messages").json()["messages"]) == 2


def test_history_is_sent_to_llm(make_client, monkeypatch):
    c = make_client()
    seen = []
    import litellm
    real = litellm.acompletion

    async def spy(**kw):
        seen.append(kw["messages"])
        return await real(**kw)

    monkeypatch.setattr(litellm, "acompletion", spy)
    chat(c, "a", "my name is Sam")
    chat(c, "a", "what is my name?")
    roles = [m["role"] for m in seen[1]]
    assert roles == ["system", "user", "assistant", "user"]


def test_system_prompt_stored_and_hidden(client):
    chat(client, "sp", "hi", system_prompt="Talk like a pirate")
    h = client.get("/sessions/sp/messages").json()["messages"]
    assert all(m["role"] != "system" for m in h)


def test_unknown_session_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}


def test_validation_422(client):
    assert client.post("/chat", json={"session_id": "s", "message": ""}).status_code == 422
    assert client.post("/chat", json={"session_id": "s", "message": "   "}).status_code == 422
    assert client.post("/chat", json={"session_id": "s", "message": "x" * 4001}).status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": "", "message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": "s" * 129, "message": "hi"}).status_code == 422
    r = client.post("/chat", content="{bad json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()
    assert client.post("/chat", json={"session_id": "s", "message": "x" * 4000}).status_code == 200


def test_cors_allows_frontend_origin(client):
    r = client.options("/chat", headers={"Origin": "http://localhost:3000",
                                         "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
