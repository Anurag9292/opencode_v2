# 7. Comparison Tables

All claims cited elsewhere in this report. `[EXTERNAL]` = runs in OpenHands' external
agent-server (not in this repo).

## 7.1 Architecture

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Language / runtime | TypeScript, **Effect-ts** services/layers | Python / FastAPI (control plane) + `[EXTERNAL]` SDK | TypeScript, **plain async** |
| Topology | Single local process | **Distributed**: control plane + sandboxed agent-server | Single local process |
| Loop location | In-process (`session/prompt.ts`) | `[EXTERNAL]` agent-server | In-process (`agent-loop.ts`) |
| Source of truth | **SQLite** (Drizzle) | **Append-only event files** (fs/S3/GCS) | **JSONL tree** file |
| Cores | Two (V1 `SessionPrompt`, V2 durable `SessionRunner`) | One control plane + external loop | One (`Agent`) |
| Primary optimization | Powerful safe local agent | Secure multi-tenant scale | Minimal hackable core |

## 7.2 Agent loop

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Loop shape | `while(true)`; inner steps via AI SDK | `[EXTERNAL]` ReAct; app_server runs a start **status machine** | Nested `while` (follow-ups × tool calls) |
| Model calls per iteration | one `process()` (may contain multiple AI-SDK steps) | `[EXTERNAL]` | exactly one `streamSimple` per turn |
| Stop condition | finish≠tool-calls & no pending tool parts (`prompt.ts:1106`) | terminal `ConversationStateUpdateEvent` `[EXTERNAL]` | no tool calls / all-`terminate` / `shouldStopAfterTurn` |
| Runaway guard | doom-loop guard (3 identical calls → ask) | `max_iterations`/budget forwarded, enforced `[EXTERNAL]` | overflow compact-and-retry; transient retry cap |
| Concurrency model | one runner per session (`run-state.ts`) | one sandbox per conversation | single active run; steering/follow-up queues |

## 7.3 Memory / context

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| History store | SQLite parts | event log | JSONL tree |
| Re-read each turn | yes (`filterCompactedEffect`) | `[EXTERNAL]` | yes (`buildSessionContext`) |
| Token counting | heuristic (`util/token`) | none in control plane (post-hoc stats) | `estimate.ts` chars/4 + schema tokens |
| Compaction | overflow + prune, protects skills (`overflow.ts`, `compaction.ts`) | `LLMSummarizingCondenser` configured here, runs `[EXTERNAL]` | threshold + overflow(+retry) + manual; structured summary (`compaction.ts`) |
| Recent-window protection | `PRUNE_PROTECT=40k` | `keep_first=2`, `max_size=240` | `keepRecentTokens=20k`, never cut at toolResult |

## 7.4 Tool execution

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Discovery | registry + `tool/*.ts` + plugins, per-model filter | preset lists on the request `[EXTERNAL]` | small built-in set + extension registry |
| Definition | `Tool.Def` (Effect Schema) | `openhands.tools` `[EXTERNAL]` | `ToolDefinition`→`AgentTool` (TypeBox/JSON schema) |
| Execution site | inside AI SDK (V1) / FiberSet (V2) | `[EXTERNAL]` sandbox | in-process batch |
| Parallel vs sequential | AI-SDK-scheduled / concurrent fibers | `(unverified)` | **parallel default**, source-order results; per-tool sequential opt-in |
| Errors | `status:error` part; `invalid` tool repair | `ObservationEvent` `[EXTERNAL]` | error tool-result; truncated→fail-all |
| Arg validation | schema decode → `InvalidArgumentsError` | `[EXTERNAL]` | `validateToolArguments` |

## 7.5 Permission / security

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Gate | built-in allow/ask/deny wildcard, default **ask** | policy selected here, enforced `[EXTERNAL]` (`NeverConfirm`/`ConfirmRisky`/`AlwaysConfirm`) | **none built-in**; extension `tool_call` hook |
| Risk analysis | pattern rules + bash arity scoping | optional **LLM security analyzer** | delegated to extension |
| Isolation | permission + external-dir guard + snapshot revert | **per-conversation sandbox** (Docker/remote), secret vaulting (LookupSecret/JWT), session API key | none built-in (extension seam) |
| Default posture | ask before risky | NeverConfirm unless enabled | run everything |

## 7.6 Prompting

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| System prompt | **per-model `.txt`** variants | **Jinja template** `[EXTERNAL]`, inputs assembled here | single code prompt or `.pi/SYSTEM.md` |
| Tool prompts | per-tool `.txt` files | `[EXTERNAL]` | one-line snippets in prompt |
| Planning prompt | `plan-*.txt` (gated) | `system_prompt_planning.j2` + `PLANNING_AGENT_INSTRUCTION` | none (extension) |
| Dynamic build | env + AGENTS.md + mcp + skills + step prompts | `system_message_suffix` + template kwargs + skills/hooks | `<project_context>` + skills + date/cwd + extension override |

## 7.7 File editing

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Edit mechanism | string-replace **+ LSP/formatter**, or `apply_patch` for GPT-5 | `[EXTERNAL]` (`openhands.tools`) | multi-edit **exact+fuzzy** string replace |
| Patch generation | real diffs; per-turn `patch` part | `[EXTERNAL]` | unified diff for **display only** |
| Concurrency safety | per-file `Semaphore` | `[EXTERNAL]` | `withFileMutationQueue` (per-realpath) |
| Git | shadow-git **snapshots + revert** | platform: clone/auth/hooks/providers | via bash/extension |

## 7.8 Planning / orchestration

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Sub-agents | **yes** (`task` tool → child session, derived perms) | **yes** (planning agent + sub-agents + ACP CLIs) | **no** (extension) |
| Plan mode | experimental, gated | **first-class agent type** (PLAN) | no |
| Todos | `todowrite` tool | `[EXTERNAL]`/PLAN.md | no (TODO.md by convention) |
| Delegation | recursion (same loop) | typed agents + inherited sandbox/config | extension-composed |

## 7.9 Extensibility

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Plugin/hook | plugin hooks (in/out mutation) | server event-callback processors + hooks proxied | **one large `ExtensionAPI`** (~30 hooks) |
| MCP | **full client + OAuth** | consumes custom + **hosts Tavily proxy** | **none** (do it in an extension) |
| Add a tool | registry/file/plugin | marketplace/`openhands.tools` | `pi.registerTool` |
| Providers | catalog + provider plugins | LLM profiles | 35 catalogs + `registerProvider` |
| Config | JSON/JSONC + md frontmatter | DI injectors + marketplaces | settings.json + flags |

## 7.10 Performance & scalability tradeoffs

| Dimension | OpenCode | OpenHands | PI |
|---|---|---|---|
| Startup latency | higher (Effect graph, SQLite, LSP) | high (sandbox provisioning: clone/setup/skills) | **low** (tiny, stdlib-ish deps) |
| Per-turn overhead | snapshots + DB writes + LSP | HTTP hops + event persistence + callbacks | minimal (JSONL append) |
| Horizontal scale | single process (scale by process) | **built for it** (stateless control plane, per-tenant sandbox, pluggable S3/GCS event store) | single process |
| Reliability | durable SQLite; V2 crash-resume; snapshot revert | event-sourced replay; status machine; retries external | JSONL resume; auto-retry; compact-and-retry |
| Blast radius of a bad tool | local FS (mitigated by permission + revert) | **contained in sandbox** | local FS (user/extension responsibility) |
| Developer experience | rich but heavy (Effect learning curve) | platform ops (Docker, DB, agent-server) | **easiest to read/hack** |

## 7.11 One-line optimization statements

- **OpenCode** optimizes for a **powerful, safe, local** agent: durability, snapshots, LSP,
  per-model prompts, sub-agents — all in one Effect-structured process.
- **OpenHands** optimizes for **secure, multi-tenant, scalable** execution: isolate the agent
  in a sandbox, event-source everything, keep the control plane stateless and pluggable.
- **PI** optimizes for a **minimal, legible, hackable** core: the smallest correct loop, with
  every non-essential capability living behind one extension API.
