import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
// A new session on each page load.
const newSessionId = () => "s-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);

function describeError(status, body) {
  if (status === 503) return "All AI providers are temporarily unavailable. Please try again in a moment.";
  if (status === 422) {
    const d = body?.detail;
    const msg = Array.isArray(d) ? d.map((e) => e.msg).join("; ") : typeof d === "string" ? d : "";
    return "Your message was rejected: " + (msg || "invalid input") + ".";
  }
  return "Something went wrong (" + status + "). Please try again.";
}

function AssistantMessage({ m }) {
  return (
    <div className="msg assistant" data-testid="assistant-message">
      <div className="text">{m.reply}</div>
      <div className="meta">
        <span className={"badge " + m.meta.resolution_source} data-testid="meta-source">{m.meta.resolution_source}</span>
        <span>model: <b data-testid="meta-model">{m.meta.model}</b></span>
        <span>latency: <b data-testid="meta-latency">{m.meta.latency_ms} ms</b></span>
        <span>in: <b data-testid="meta-input-tokens">{m.meta.input_tokens}</b></span>
        <span>out: <b data-testid="meta-output-tokens">{m.meta.output_tokens}</b></span>
        {m.meta.key_id && <span className="dim">{m.meta.key_id}{m.meta.fallback_attempts ? ` (after ${m.meta.fallback_attempts} failed)` : ""}</span>}
      </div>
    </div>
  );
}

export default function App() {
  const [sessionId] = useState(newSessionId);
  const [items, setItems] = useState([]); // {kind: user|assistant|error, ...}
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [simulate, setSimulate] = useState("");
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [items, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setItems((p) => [...p, { kind: "user", text }]);
    try {
      const headers = { "Content-Type": "application/json" };
      if (simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();
      const body = { session_id: sessionId, message: text };
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
      const res = await fetch(API + "/chat", { method: "POST", headers, body: JSON.stringify(body) });
      let data = null;
      try { data = await res.json(); } catch { /* non-JSON body */ }
      if (!res.ok || !data?.reply) {
        setItems((p) => [...p, { kind: "error", text: describeError(res.status, data) }]);
      } else {
        setItems((p) => [...p, { kind: "assistant", reply: data.reply, meta: data.metadata }]);
      }
    } catch {
      setItems((p) => [...p, { kind: "error", text: "Cannot reach the server. Check your connection and try again." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>LLM Chatbot</h1>
        <span className="dim">session {sessionId}</span>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>System prompt (optional)
          <textarea data-testid="system-prompt-input" rows={2} value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)} placeholder="e.g. You are a pirate." />
        </label>
        <label>Failover test header (optional, demo only)
          <input value={simulate} onChange={(e) => setSimulate(e.target.value)} placeholder="key_1=429" />
        </label>
      </details>

      <main className="chat" aria-live="polite">
        {items.length === 0 && <p className="dim empty">Say hello to start the conversation.</p>}
        {items.map((m, i) =>
          m.kind === "assistant" ? <AssistantMessage key={i} m={m} /> :
          m.kind === "user" ? <div key={i} className="msg user"><div className="text">{m.text}</div></div> :
          <div key={i} className="msg error" role="alert">{m.text}</div>
        )}
        {busy && <div className="msg assistant dim">Thinking…</div>}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea data-testid="chat-input" rows={1} value={input} placeholder="Type a message…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <button data-testid="send-button" onClick={send} disabled={busy}>Send</button>
      </footer>
    </div>
  );
}
