# 1. Overview, Thesis, and High-Level Architecture

## 1.1 The one fundamental difference

All three are "a while-loop that calls a model, runs the tools the model asks for, feeds the
results back, and repeats until the model stops." They differ in **where that loop runs and
who owns the state around it**:

| | OpenCode | OpenHands | PI |
|---|---|---|---|
| **Where the loop runs** | In-process, local (single process) | In an **external sandboxed `agent-server`** (`app_server` is only a control plane) | In-process, local (single process) |
| **Structuring principle** | Effect-ts services/layers; durable SQLite transcript; per-turn git snapshots | Event-sourcing across an HTTP boundary; push webhooks; per-conversation sandbox | Minimal plain-async core + a large extension API surface |
| **Optimizes for** | Powerful, safe **local** agent | Secure, multi-tenant, **scalable cloud** execution | **Minimal, hackable** local core |
| **Philosophy** | "Batteries included, safety via permission + snapshot revert" | "Isolate the untrusted agent; the server only orchestrates and records" | "Ship a tiny core; make everything else an extension" |

This single axis — **monolithic-local (OpenCode, PI) vs distributed-control-plane
(OpenHands)** — explains almost every downstream difference (state model, streaming,
security, extensibility).

## 1.2 Methodology & the OpenHands boundary

Per the analysis requirements we read docs first, then verified against code. One caveat
dominates the OpenHands analysis and is verified in the code:

> **`openhands_all/app_server` does NOT contain the agent loop.** The model streaming,
> tool-call detection, tool execution, permission enforcement, and system-prompt rendering
> all happen inside the external `openhands-agent-server` (using `openhands.sdk` /
> `openhands.tools`), which is **not vendored** in this repo (no `openhands.sdk` /
> `openhands.agent_server` source on disk; the only local package is `openhands.app_server`).
> Verified: dispatch is `POST {agent_server_url}/api/conversations`
> (`live_status_app_conversation_service.py:_start_app_conversation`, `:486`), events return
> via inbound webhook (`event_callback/webhook_router.py:on_event`, `:468`).

So for OpenHands, "the loop" is described from what `app_server` *controls and observes*;
internal loop mechanics are marked `[EXTERNAL]`.

---

## 1.3 OpenCode — high-level architecture

**Runtime:** TypeScript on **Effect (effect-ts v4-beta)** — every subsystem is a
`Context.Service` with a `Layer` implementation and an explicit dependency graph
(`LayerNode.make`). Callback boundaries (Vercel AI SDK tool `execute`, plugins, node-pty)
cross into Effect via `EffectBridge` (`packages/opencode/src/effect/bridge.ts`).

**Two coexisting cores (verified):**
- **V1 (production path):** `packages/opencode/src/session/prompt.ts` — `SessionPrompt.runLoop`
  (`:1081`), a literal `while (true)` (`:1088`).
- **V2 (durable path):** `packages/core/src/session/runner/llm.ts` — `SessionRunner.run`
  (`:383`), a durable runner with input-admission, run-coordinator, and crash-resume
  scaffolding (docstring `:43–91`).

**Major components (files):**
- `session/prompt.ts` — the turn loop, user-message creation, subtask/command/shell orchestration.
- `session/processor.ts` — one provider turn: consumes the normalized `LLMEvent` stream, drives the part state machine, settles tool calls (`SessionProcessor.process`, `:627`).
- `session/llm.ts` — provider seam: Vercel AI SDK `streamText` (`:280`) normalized to `LLMEvent` (`LLMAISDK.toLLMEvents`, `:376`); optional native runtime.
- `tool/registry.ts` + `tool/tool.ts` — tool discovery/definition.
- `permission/index.ts` — allow/ask/deny wildcard engine.
- `snapshot/index.ts` — shadow-git per-turn file snapshots.
- `session/session.ts` — SQLite/Drizzle session+message+part CRUD (source of truth).
- `event-v2-bridge.ts` + `bus/global.ts` — event publish boundary.
- `mcp/`, `plugin/`, `skill/`, `config/`, `lsp/` — extensibility.

**Control flow:** HTTP handler (`server/.../session.ts` `prompt`) → `SessionPrompt.prompt`
→ persist user message → `loop()` → `SessionRunState.ensureRunning` (one runner per session)
→ `runLoop` → per iteration: load history → resolve tools + system prompt → `processor.process`
(one provider turn) → tools execute inside the AI SDK → results become message parts → loop
until the stop condition.

---

## 1.4 OpenHands — high-level architecture

**Runtime:** Python / FastAPI. `app_server` is a **stateless-ish control plane**; the agent
is an **event-sourced** actor living in a **per-conversation sandbox**.

**The layer diagram (verified):**
```
Client ──HTTP──▶ app_server (FastAPI, this repo)
                   │ 1. provision sandbox (Docker/remote) running the agent-server
                   │ 2. assemble Agent + StartConversationRequest (LLM, tools, skills, hooks, secrets, policy)
                   │ 3. POST {agent_server_url}/api/conversations         (start turn)
                   │ 4. POST .../conversations/{id}/events                (user input)
                   ▼
             agent-server  [EXTERNAL, in sandbox, uses openhands.sdk/tools]
                   │  runs the loop: system prompt → LLM.stream → ActionEvent (tool call)
                   │  → confirmation/security gate → tool exec → ObservationEvent → repeat → MessageEvent
                   └──HTTP POST /api/v1/webhooks/events/{id}──▶ app_server (persist + callbacks)
```

**Major components (files):**
- `app_conversation/live_status_app_conversation_service.py` — **the orchestrator**: status machine, sandbox provisioning, request assembly (`_build_start_conversation_request_for_user`, `:1630`), dispatch (`:486`).
- `app_conversation/app_conversation_service_base.py` — repo clone/init, setup scripts, git hooks, condenser, confirmation-policy selection (`_select_confirmation_policy`, `:677`).
- `event_callback/webhook_router.py` — inbound webhook (`on_event`, `:468`): persist + reconcile + fan out callbacks.
- `event/event_service_base.py` (+ filesystem/aws/gcp backends) — append-only, one-JSON-file-per-event storage.
- `sandbox/{docker,remote}_sandbox_service.py` — runtime provisioning; injects the webhook callback URL (`OH_WEBHOOKS_0_BASE_URL`).
- `settings/settings_models.py` — source of LLM/agent/condenser/confirmation/security/skills config.
- `mcp/mcp_router.py` — a self-hosted MCP server (Tavily proxy) so the sandbox never sees the Tavily key.

**Control flow:** `POST /api/v1/app-conversations` → `app_conversation_router.start_app_conversation`
(`:365`, returns first status immediately, drives the rest in a background task) →
`LiveStatusAppConversationService._start_app_conversation` status machine
(`WORKING → WAITING_FOR_SANDBOX → PREPARING_REPOSITORY → RUNNING_SETUP_SCRIPT →
SETTING_UP_GIT_HOOKS → SETTING_UP_SKILLS → STARTING_CONVERSATION → READY`) → dispatch to
agent-server → **[EXTERNAL loop]** → events arrive at `webhook_router.on_event` → persisted +
callbacks (e.g. title generation) → client reads via REST (`event/event_router.py`).

---

## 1.5 PI — high-level architecture

**Runtime:** TypeScript, **plain async/Promises** (verified: zero `effect` imports in
`packages/agent` and `packages/coding-agent`). Deliberately minimal.

**Package layout & dependency direction:** `coding-agent → agent → ai`.
- `packages/agent` — the model-agnostic loop (`Agent`, `runAgentLoop`/`runLoop`).
- `packages/coding-agent` — the harness/SDK/CLI: sessions, tools, system prompt, extensions, modes.
- `packages/ai` — providers + `streamSimple` (35 provider catalogs, SSE/websocket transports).
- `packages/tui` — terminal UI.

**Major components (files):**
- `packages/agent/src/agent-loop.ts` — `runLoop`, `streamAssistantResponse`, `executeToolCalls`, `prepareToolCall`.
- `packages/agent/src/agent.ts` — `Agent` class: state, event subscription, steering/follow-up queues.
- `packages/coding-agent/src/core/agent-session.ts` — `AgentSession`: wires persistence, extensions, compaction, retry; installs the `beforeToolCall`/`afterToolCall` hooks.
- `packages/coding-agent/src/core/sdk.ts` — `createAgentSession` factory + provider `streamFn` wrapper.
- `packages/coding-agent/src/core/session-manager.ts` — JSONL tree persistence (`id`/`parentId`, branching).
- `packages/coding-agent/src/core/system-prompt.ts` + `messages.ts` — prompt build + `convertToLlm`.
- `packages/coding-agent/src/core/extensions/{runner,types,loader}.ts` — **the extensibility core**.
- `packages/coding-agent/src/core/compaction/compaction.ts` — summarize-and-cut compaction.

**Control flow:** mode (interactive/print/rpc) → `AgentSession.prompt` (preflight: extension
command → `emitInput` → skill/template expansion → model+auth validation → compaction check →
`emitBeforeAgentStart`) → `Agent.prompt` → `runAgentLoop`/`runLoop` → per iteration:
`transformContext` → `convertToLlm` → build `Context` → `streamFn`→`streamSimple` → detect
tool calls → `prepareToolCall` (validate + `beforeToolCall` permission hook) → execute →
tool-result messages → loop; persistence + tracing happen as event subscribers.

---

## 1.6 What each project *is*, in one line

- **OpenCode**: a local coding-agent **engine** with production concerns (durability, snapshots, LSP, MCP, sub-agents) folded into a single Effect-structured process.
- **OpenHands**: a **platform** — the agent is an isolated, event-sourced, sandboxed workload; the repo we have is the orchestration/persistence brain around it.
- **PI**: a **library/CLI kernel** — the smallest correct loop, with an extension seam where every "feature" plugs in.
