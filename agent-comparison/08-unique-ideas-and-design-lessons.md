# 8. Unique Ideas & Design Lessons

## 8.1 Innovations unique to each project

### OpenCode — ideas the others don't have
1. **Per-turn shadow-git snapshots + revert** (`snapshot/index.ts`). A separate git dir per
   project captures a `write-tree` before each turn and computes a per-turn `patch` part;
   sessions can time-travel over file state (`session/revert.ts`). Neither OpenHands' event log
   nor PI's JSONL captures *filesystem* state per turn — this is genuine undo for the agent's
   edits.
2. **Per-model system-prompt variants** (`prompt/{anthropic,gpt,gemini,beast,codex,kimi,...}.txt`
   selected by model id). The harness adapts its prompting to the model family rather than
   using one prompt for all.
3. **Model-aware tool selection** (`registry.tools(model)`): e.g. `apply_patch` for GPT-5-class
   models, `edit`/`write` otherwise — the toolset itself changes per model.
4. **Bash arity permission scoping** (`web-tree-sitter` + `BashArity`): permission patterns are
   scoped to the *specific files/dirs a command touches*, not just the command string.
5. **Two coexisting cores** with a durable V2 (`core/session/runner`) doing input-admission +
   run-coordinator + crash-resume — production durability without abandoning the simple V1.
6. **LSP-in-the-loop**: edits trigger formatter + LSP diagnostics inline.

### OpenHands — ideas the others don't have
1. **Control-plane / sandboxed-agent split with push webhooks.** The agent is an untrusted,
   isolated workload; the server only assembles a request, dispatches it, and *receives events
   back* (`webhook_router.on_event`). This is the only design of the three that can safely run
   arbitrary agent code multi-tenant.
2. **Secret vaulting via `LookupSecret` + scoped JWT.** Raw provider/git tokens never enter the
   sandbox; the agent fetches them at runtime from a webhook using a time-boxed JWT
   (`_setup_secrets_for_git_providers`, `webhook_router.get_secret`). Security-first credential
   handling absent in the local agents.
3. **A self-hosted MCP *proxy*** (`mcp/mcp_router.py:init_tavily_proxy`) so a third-party API
   key (Tavily) stays in the control plane, out of the sandbox — MCP used as a security boundary.
4. **Event sourcing as the primary state model**, with pluggable backends (fs/S3/GCS) and
   trajectory export — the transcript *is* an append-only audit log across a process boundary.
5. **First-class planning agent** (`AgentType.PLAN`) as a distinct agent with its own prompt
   template and a hard "plan-then-hand-off" boundary.
6. **Off-hot-path event callbacks** (`SetTitleCallbackProcessor`) with deliberate connection
   management to avoid pool exhaustion — server-side extensibility that never blocks the agent.
7. **Marketplace-composed skills** (instance/org/user precedence) and **ACP agents** (wrapping
   external CLIs like Claude Code/Codex as agents).

### PI — ideas the others don't have
1. **The extension API *is* the architecture.** ~30 event hooks + registration methods
   (`ExtensionAPI`) mean permissions, MCP, sub-agents, plan mode, and even the LLM provider are
   all extensions. The core stays tiny on purpose. "No MCP / no sub-agents / no permissions" is
   a *feature*: the seam is uniform.
2. **Steering vs follow-up queues** (`Agent.steer`/`followUp`): interrupt-and-redirect *while
   tools run* vs queue-for-after — a genuinely different interaction model, delivered as a core
   primitive.
3. **Fuzzy, line-ending/BOM-preserving multi-edit** (`edit-diff.ts`: NFKC + smart-quote/dash
   normalization, uniqueness + non-overlap enforcement) — the most robust *pure-string* editor,
   no patch format required.
4. **Compact-and-retry on overflow as a distinct path** from transient retry, with a structured
   summary schema (`## Goal / Progress / Key Decisions / Next Steps / Critical Context`) and
   iterative summary merging.
5. **JSONL session *tree*** with in-place branching/fork/clone — human-readable, git-friendly,
   zero-infra time travel over *conversation* state.
6. **35 provider catalogs behind one `streamSimple`** with SSE/websocket transports and a
   provider-registration extension — broad model coverage with a tiny core seam.

## 8.2 Design lessons: what to borrow for a next-gen agent

If building a new coding agent from scratch, borrow deliberately:

**From PI — the core:**
- **Start with PI's loop.** A model-agnostic `runLoop` (one provider call → detect tool calls →
  execute → feed back) with **plain async** is the most legible foundation. Keep the core
  ignorant of persistence and UI (events + subscribers).
- **Make persistence a subscriber, not a call.** PI's `message_end → append` (and the
  mini-agent's "store is the source of truth, re-read each turn") is the discipline that later
  enables resume, multi-observer UIs, and sub-agents *for free*.
- **Steering/follow-up queues** as a core primitive — they cost little and change UX a lot.
- **One uniform extension seam** so features are additive; resist baking features into the core.

**From OpenCode — the safety and richness:**
- **Message-of-typed-parts with a tool state machine** (`pending→running→completed|error`
  carrying its own output). It makes streaming, persistence, and "failures are data" fall out
  naturally. Adopt this data model early.
- **Per-turn snapshots + revert.** Cheap insurance; the single best local-safety feature. Even
  a shadow-git per project is worth it.
- **A real permission engine** (allow/ask/deny, wildcard, last-match-wins, default ask) — the
  right default for a *local* agent, far better than PI's "run everything."
- **Per-model prompt/tool selection.** Model families genuinely differ; one prompt is a
  compromise.
- **A durable runner path (V2)** for crash-resume when you outgrow a single-shot loop.

**From OpenHands — the platform:**
- **Sandbox the agent + event-source the transcript** the moment you go multi-tenant or run
  untrusted tool calls. The control-plane/agent split with **push webhooks** is the scalable,
  secure topology.
- **Secret vaulting** (never put raw tokens in the execution environment; fetch via a
  short-lived scoped credential) — mandatory for a hosted product.
- **A first-class planning agent** with a hard plan→execute boundary beats a "plan mode" flag
  bolted onto one loop for complex tasks.
- **Off-hot-path callbacks** (title generation, analytics, indexing) so side work never blocks
  the agent.
- **Pluggable storage backends** (fs/S3/GCS) behind one event-store interface.

**The synthesis (a recommended target architecture):**
> PI's tiny async loop + OpenCode's typed-parts/state-machine transcript, permission engine, and
> per-turn snapshots + a PI-style extension API — all runnable **locally in-process** for the
> single-user case, but with the transcript modeled as an **event log** and tool execution
> behind an interface so that the *same* loop can be dropped into an **OpenHands-style sandbox +
> control plane** for the multi-tenant case without rewriting the agent. In short: **PI's core,
> OpenCode's safety/data-model, OpenHands' deployment topology** — chosen per deployment, not
> baked in.

## 8.3 The tradeoff each choice implies

| Choice | Buys you | Costs you |
|---|---|---|
| In-process loop (OpenCode, PI) | Low latency, simple call graph, easy debugging | Weak isolation; scaling = more processes |
| Control plane + sandbox (OpenHands) | Security, multi-tenancy, horizontal scale | Latency (provisioning + HTTP hops), operational complexity |
| Built-in permission engine (OpenCode) | Safe local defaults | More core code; UX friction (prompts) |
| No permissions (PI) | Tiny core; run-anywhere | Unsafe by default; safety is the user's/extension's job |
| SQLite transcript (OpenCode) | Queryable, paginated, multi-observer | Schema/migrations; heavier |
| Event log (OpenHands) | Cross-process contract + audit + replay | Rebuild cost; eventual-consistency reasoning |
| JSONL tree (PI) | Human-readable, branchable, zero-infra | Linear scans; no rich queries |
| Effect runtime (OpenCode) | Structured concurrency, typed deps, resource safety | Steep learning curve; heavier reading |
| Plain async (PI) | Anyone can read it | You hand-roll queues/cancellation |
| Batteries-included (OpenCode) | Works great out of the box | Bigger surface to maintain |
| Extension-everything (PI) | Minimal, adaptable | You assemble your own agent |
