# 3. Tools, Execution, and the Runtime Environment

## 3.1 How tools are discovered

### OpenCode — registry with built-ins + filesystem + plugins, per-model filtering
`tool/registry.ts` (`ToolRegistry.Service`). Built-ins are hard-wired in an `Effect.all`
block (`:204–222`) and ordered in `builtin[]` (`:226–244`):
`invalid, question?, shell, read, glob, grep, edit, write, task, fetch(webfetch), todo,
search(websearch), skill, patch(apply_patch)` + optional `execute`(code-mode), `lsp`, `plan`.
**Custom tools** come from (a) filesystem `{tool,tools}/*.{js,ts}` scanned via
`Glob.scanSync` and dynamically imported (`:178–192`), and (b) plugin `p.tool` maps
(`:194–199`), both funneled through `fromPlugin` (`:120`). `registry.tools(model)` (`:286`)
**filters per model** (e.g. `apply_patch` only for GPT-5-class models, else `edit`/`write`,
`:292–295`) and runs the `tool.definition` plugin hook. A tool is a `Tool.Def` (`tool/tool.ts:55`):
`{ id, description, parameters (Effect Schema), execute(args, ctx) }`; `Tool.define` wraps the
schema decode + auto-truncation + the canonical `InvalidArgumentsError` (`tool.ts:24`).

### OpenHands — a preset list attached to the request `[EXTERNAL execution]`
Tool *selection* is in `app_server` (`_build_start_conversation_request_for_user`, `:1780`):
`get_planning_tools(...)` (PLAN) vs `register_builtins_agents(enable_browser=True)` +
`get_default_tools(enable_browser=True, enable_sub_agents=...)` (DEFAULT), plus
`get_registered_agent_definitions()` for sub-agents. A `switch_llm` tool is force-added when
≥2 LLM profiles exist (`:1815`). The tool *implementations and execution* are all `[EXTERNAL]`
in `openhands.tools`; there is no tool `.run()` in this repo. MCP tools are added via
`_add_system_mcp_servers` (`:1254`).

### PI — a small built-in set + registry + extension tools
Built-ins: `read, write, edit, bash, grep, find, ls`
(`coding-agent/src/core/tools/*`, aggregated by `tools/index.ts:createAllToolDefinitions`).
`AgentSession._buildRuntime` wraps `ToolDefinition`s into `AgentTool`s
(`tools/tool-definition-wrapper.ts:wrapToolDefinition`) and `setActiveToolsByName` sets
`agent.state.tools`. Extension tools are registered via the extension API
(`ExtensionAPI.registerTool`) and merged into the registry. Allow/deny via `--tools`/`--exclude-tools`.

## 3.2 How tool calls are executed + parallel vs sequential

| | Execution site | Parallelism |
|---|---|---|
| **OpenCode** | V1: tools execute **inside the Vercel AI SDK** — `SessionTools.resolve` (`session/tools.ts:41`) builds AI-SDK `tool({...})` objects whose `execute` bridges into Effect (`EffectBridge`, `tools.ts:103`); the SDK schedules them. V2: `runTurnAttempt` starts each call into a **`FiberSet`** and awaits all (`core/session/runner/llm.ts:250–271`). | V1: whatever the AI SDK does (can be concurrent per step). V2: **genuinely concurrent** fibers. |
| **OpenHands** | `[EXTERNAL]` agent-server | `(unverified)` — external |
| **PI** | `agent-loop.ts:executeToolCalls` → `executeToolCallsParallel` (default) or `Sequential`; per-tool `executionMode:"sequential"` forces the whole batch sequential | **Parallel by default** (`Promise.all`), preserving assistant **source order** for persisted tool-result messages; sequential opt-in |

Both OpenCode and PI default to concurrency where safe. PI is the most explicit: parallel
finalize, but results are re-ordered to assistant source order before persistence.

## 3.3 Error handling & retries — "failures are data"

All three turn tool failures into **model-readable results**, never crashes — verified in each:
- **OpenCode:** `failToolCall` writes a `status:"error"` tool part with a message
  (`processor.ts:186`); bad/unknown calls remap to the `invalid` tool via AI SDK
  `experimental_repairToolCall` + `InvalidArgumentsError` (`llm.ts:296`). Permission rejection
  sets `ctx.blocked` (stops cleanly).
- **OpenHands:** tool errors become `ObservationEvent`s `[EXTERNAL]`; the control plane just
  persists them.
- **PI:** `prepareToolCall`/`executePreparedToolCall` catch thrown errors →
  `createErrorToolResult` (`is_error` tool-result message); truncated (`stopReason:"length"`)
  responses **fail all tool calls** via `failToolCallsFromTruncatedMessage` (never execute
  possibly-truncated args).

**Model/transport retries:**
- **OpenCode:** retry/repair at the provider seam (AI SDK), plus provider transforms.
- **OpenHands:** `[EXTERNAL]`; `app_server` forwards budgets and receives error events.
- **PI:** explicit auto-retry with exponential backoff for *transient* errors only
  (`agent-session.ts:_prepareRetry`, `_isRetryableError`; `ai/src/utils/retry.ts:isRetryableAssistantError`
  — excludes quota/billing, matches overloaded/429/5xx/timeouts). Context overflow is routed to
  compaction, not retry.

## 3.4 Permission / gate models — the biggest philosophy split

| | Model | Default | Where |
|---|---|---|---|
| **OpenCode** | **Rich built-in gate**: `allow / ask / deny` wildcard rules, **last-match-wins**, **default `ask`**; human approval parks on a `Deferred`; `"always"` adds a rule and auto-resolves pending; per-tool + per-agent rulesets; bash arity scopes patterns to touched paths | **ask** | `permission/index.ts:evaluate` (`:28`), `ask` (`:67`), `reply` (`:109`) |
| **OpenHands** | **Policy selected in control plane, enforced `[EXTERNAL]`**: `NeverConfirm` / `ConfirmRisky` (LLM risk analyzer) / `AlwaysConfirm` (`_select_confirmation_policy`, `:677`); POSTed to agent-server (`_set_security_analyzer_from_settings`, `:690`) | `NeverConfirm` (confirmation off) | `app_conversation_service_base.py` |
| **PI** | **No built-in permission at all** (verified). The *only* gate is the extension `tool_call` hook (`beforeToolCall` → `emitToolCall`, block short-circuit). No handler ⇒ tools run after schema validation | **run everything** | `agent-session.ts:_installAgentToolHooks`; `extensions/runner.ts:emitToolCall` |

This is a clean three-way spectrum: **OpenCode = built-in rule engine**, **OpenHands =
policy + LLM risk classifier enforced in a sandbox**, **PI = no policy, it's your extension's job**.

## 3.5 Execution environment, sandboxing, security

| | Shell execution | Isolation | Security posture |
|---|---|---|---|
| **OpenCode** | `tool/shell.ts` + `prompt.ts:shellImpl` (`:451`); spawns via `Shell.preferred`, `TERM=dumb`, `forceKillAfter:"3s"`; `web-tree-sitter` parses commands + `BashArity` scopes permissions to touched dirs | **No OS sandbox in core** — safety = permission gate + external-directory guards + **snapshot revert**. A separate `packages/containers` exists for containerized exec | Local trust; user approves risky actions; can undo via snapshots |
| **OpenHands** | `[EXTERNAL]` inside the sandbox | **Per-conversation sandbox** (Docker or remote); the agent-server *runs inside it*; app_server reaches it via an exposed port; secrets injected as `LookupSecret` (JWT-scoped, redeemed at a webhook) or `StaticSecret` so raw tokens never enter the sandbox; per-sandbox `X-Session-API-Key` (hash-stored, rotated) | **Strong isolation by construction** — the untrusted agent is boxed; the control plane holds secrets and identity |
| **PI** | `tools/bash.ts` — **fresh `child_process.spawn` per command** (no persistent shell), no default timeout, `killProcessTree` on abort/timeout | **No sandbox** — local process; `commandPrefix`/`spawnHook` seams let an extension add remote/sandboxed exec | Local trust; isolation is an extension concern |

The pattern mirrors the loop location: **OpenHands treats the agent as untrusted and sandboxes
it**; OpenCode and PI run locally and rely on permission (OpenCode) or the user's environment/
extensions (PI).

## 3.6 Summary

- Tool **discovery**: OpenCode (registry + fs + plugins + per-model filter) is the richest;
  PI (small set + extension registry) is the leanest; OpenHands (preset list on a request) is
  selection-only because execution is external.
- Tool **execution**: OpenCode delegates to the AI SDK / fibers; PI runs an explicit
  parallel-with-source-order batch; OpenHands executes `[EXTERNAL]`.
- **Safety** is where philosophy shows most: a built-in rule engine (OpenCode), a
  sandbox + risk classifier (OpenHands), or nothing-by-default + a hook (PI).
