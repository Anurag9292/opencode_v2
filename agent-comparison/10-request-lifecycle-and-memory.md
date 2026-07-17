# 10. Anatomy of a Request: Agentic Logic, Memory & Context Management

This document is the **cognition-focused** companion to the rest of the report. It ignores
plumbing (HTTP, TUI, Effect layers) and answers one question:

> A user types **"Build me a todo app."** What does each agent *actually do with that request* —
> how does it decide what to do, where does it keep what it learns, how does it decide what to
> forget, and what do its sub-agents do?

It is written to stand alone (some overlap with `02-agent-loop-and-state.md` and
`04-context-filesystem-prompts.md`, which have the full mechanics). Every claim carries a
`file:symbol` citation. OpenHands' real loop runs in an external, non-vendored agent-server, so
those internals are tagged `[EXTERNAL]`.

---

## 0. The one thing to internalize first

An LLM has **no memory**. The only thing a model ever sees is the array of messages you hand it
on *this* call. So "agent memory" is really three tiers, and every design decision below is
about moving information between them:

1. **Working context** — the token window sent to the model *this turn*. Scarce, expensive,
   volatile. Rebuilt from scratch every turn.
2. **Durable transcript** — the append-only record of everything that happened (the "store").
   Cheap, large, persistent. This is the **source of truth**.
3. **Derived / retrieved memory** — compressed or selectively-surfaced views: summaries, skill
   snippets, plan files, file snapshots, branch summaries. This is where the "keep the relevant
   info, drop the rest" intelligence lives.

**The shared invariant across all three agents:** the loop re-reads the durable transcript
every turn and *reconstructs* the working context from it. "Memory management" = the policy
that decides **what slice of the transcript (plus which derived memory) gets rebuilt into the
window** before each model call.

- OpenCode: `MessageV2.filterCompactedEffect(sessionID)` re-read each turn (`session/prompt.ts:1092`).
- OpenHands: history *is* the event log; the window is rebuilt `[EXTERNAL]` from persisted events.
- PI: `SessionManager.buildSessionContext()` walks the JSONL tree and rebuilds the active path.

> **Headline finding (verified across all three cores):** **none of them use embeddings /
> vector search / semantic RAG** over the conversation. `grep` for `embedding|vector|faiss|
> pgvector|semantic search` returns nothing relevant in any core. "Relevance" is achieved by
> **recency windows + summarization + structured artifacts** (skills, plan files, snapshots,
> branch summaries), *not* by similarity retrieval. This matters: memory is *chronological and
> lossy-compressed*, not *associative*.

---

## 1. "Build me a todo app" — OpenCode

### 1a. Ingestion & decomposition
OpenCode runs a single **primary agent** in a `while (true)` loop (`session/prompt.ts:runLoop`,
`:1081`). It does **not** force a plan step. For "build me a todo app" it will typically, over
successive turns: read/scaffold files (`write`), edit them (`edit`), run commands (`shell`),
and check its work — deciding turn-by-turn. Two decomposition tools are available if the model
chooses them:
- **`todo` / `todowrite`** — an in-context scratchpad the model uses to track sub-steps
  ("create package.json", "add index.html", "wire the add-item handler"). This is *planning as
  data inside the transcript*, not a separate agent.
- **`task` tool** (`tool/task.ts`, `TaskTool`) — spawns a **sub-agent** (§1e).
- Optional **plan mode** (`tool/plan.ts`, gated behind `flags.experimentalPlanMode`) writes a
  plan to `.opencode/plans/*.md`.

### 1b. Where the turn's memory is written
Into **SQLite** (Drizzle) as a `Message` composed of typed **parts**
(`schema/session-message.ts`): `TextPart`, `ReasoningPart`, `ToolPart`, `StepStartPart`,
`PatchPart`, `FilePart`, `SnapshotPart`. A tool call is a **state machine part**
`pending → running → completed | error` that **carries its own output**
(`ToolStatePending/Running/Completed/Error`, `session-message.ts:81–119`). So the full story of
"I ran `write index.html` and here's what happened" lives *inside one part*. Persistence is
incremental: `updatePartDelta` writes as tokens stream (`processor.ts:299`), so a crash
mid-turn loses nothing.

### 1c. What re-enters the window each turn
`session/prompt.ts:1257` assembles: `[...environment, ...instructions, mcp?, skills?] +
model-messages`. Concretely:
- `SystemPrompt.environment` — `<env>` block: cwd, worktree, git status, platform, date, model
  (`system.ts:60`) — a small, always-fresh "where am I" memory.
- `Instruction.system` — `AGENTS.md`/`CLAUDE.md` walked up from cwd, plus instruction files near
  files being read (`instruction.ts`). Project conventions re-injected every turn.
- `MessageV2.toModelMessagesEffect(msgs)` — the (compaction-filtered) transcript.

### 1d. Purge / keep policy — how it forgets
As the todo-app session grows (lots of file reads, shell output), the window fills. Two
mechanisms:
- **Overflow detection** — `session/overflow.ts:isOverflow` (`:22`) compares total tokens to
  `usable()` = context window minus a reserved buffer `COMPACTION_BUFFER = 20_000`
  (`overflow.ts:8`). Checked in the loop (`prompt.ts:1161`) and on `step-finish` /
  `ContextOverflowError`.
- **Compaction + prune** — `SessionCompaction.Service` (`session/compaction.ts`). Pruning walks
  **backward** through tool parts accumulating tokens until it has protected `PRUNE_PROTECT =
  40_000` tokens of recent tool output (`:241`, `:271`), **always keeping `skill` outputs**
  (`PRUNE_PROTECTED_TOOLS = ["skill"]`, `:31`; `:267`), and only prunes if it can reclaim more
  than `PRUNE_MINIMUM = 20_000` (`:278`). Older content is replaced by a **summary message**;
  `MessageV2.filterCompacted` (`message-v2.ts:521`) then *hides the pre-summary history* from the
  window while it remains in SQLite.

**Net effect for the todo app:** early throwaway detail (the full text of a `README` it read on
turn 2, verbose `npm install` output) gets pruned/summarized; recent edits and skill outputs
stay verbatim; the durable SQLite copy is never lost (you can revisit it).

### 1e. Sub-agent memory
The `task` tool spawns a **child session running the same loop recursively**
(`tool/task.ts` → `SessionPrompt.prompt`). Crucially:
- The child has its **own transcript** (own SQLite session) — its intermediate reasoning does
  **not** pollute the parent's window. Only its **final text is returned to the parent as the
  tool result** — a deliberate *context-isolation + compression* move.
- The child runs with a **derived, narrowed permission ruleset**
  (`agent/subagent-permissions.ts:deriveSubagentSessionPermission`).
- Can run in the **background** (`BackgroundJob.Service`).
So "have a sub-agent write the test suite" keeps all the noisy trial-and-error out of the main
agent's memory; the main agent only remembers "the sub-agent produced these tests."

### 1f. A unique memory tier: filesystem snapshots
Beyond conversation memory, OpenCode snapshots **file state** per turn via a shadow git repo
(`snapshot/index.ts`): `snapshot.track()` before a turn (`processor.ts:102`), a `patch` part of
changed files on `step-finish` (`:457`), and `restore`/`revert` (`session/revert.ts`). This is
*memory of what the code looked like*, orthogonal to the transcript — you can rewind the todo
app's files to any prior turn.

---

## 2. "Build me a todo app" — OpenHands

> Reminder: the loop is `[EXTERNAL]`. `app_server` assembles the request, dispatches it, and
> records the event stream that comes back.

### 2a. Ingestion & decomposition
OpenHands makes decomposition a **first-class agent type** (`AgentType.DEFAULT` vs `PLAN`,
`app_conversation_models.py:64`). For a big ask like "build me a todo app" the product can route
to the **planning agent**: system prompt swapped to `system_prompt_planning.j2`, tools swapped
to `get_planning_tools(...)`, and a `PLANNING_AGENT_INSTRUCTION` (`:194`) that tells it to
**produce a plan and hand off — not execute**. The plan is written to a **`PLAN.md`** file
(`_compute_plan_path`, `:1104`). Then the default (coding) agent executes against that plan.
So decomposition can be a *separate agent producing a durable artifact* the executor reads.

### 2b. Where the turn's memory is written
As an **append-only event log**: every step is an `Event` — `MessageEvent`, `ActionEvent`
(a tool call), `ObservationEvent` (a tool result), `ConversationStateUpdateEvent`. The
agent-server POSTs each to the webhook (`event_callback/webhook_router.py:on_event`, `:468`),
which persists it as **one JSON file per event**
(`event/event_service_base.py:save_event`, `:190`; path `{user}/v1_conversations/{id.hex}/
{event}.json`). Event sourcing is the natural memory model here precisely because the *producer*
(sandboxed agent) and the *store* (control plane) are different processes — an append-only log
is the clean cross-process contract, and it doubles as the audit log / trajectory export
(`iter_events_for_export`, `:145`).

### 2c. What re-enters the window each turn
Rebuilt `[EXTERNAL]` from the event stream + the assembled `AgentContext`. `app_server` controls
the *inputs*: system-prompt template + kwargs, `system_message_suffix` (planning boundary,
`<HOST>`, shallow-clone context), attached **skills/microagents** and **hooks**
(`_build_start_conversation_request_for_user`, `:1630`). Skills are **retrieval-augmented
instructions**: loaded via `skill_loader.load_skills_from_agent_server` (`:505`) and attached
with `KeywordTrigger` / `TaskTrigger` — i.e. a skill's text is surfaced into context **only when
the conversation matches its trigger**, the closest thing here to selective recall (still
trigger-based, not embedding-based).

### 2d. Purge / keep policy — how it forgets
Configured here, executed `[EXTERNAL]`: a **`LLMSummarizingCondenser`**
(`app_conversation_service_base.py:_create_condenser`, `:614`) with SDK defaults **`max_size=240,
keep_first=2`** (`:630`), overridable via `condenser_max_size` (`:643`), with its own
`usage_id` (`condenser` / `planning_condenser`). Semantics: **keep the first `keep_first`
events** (the original task framing — never forget *why* we're building the todo app), and once
the event count exceeds `max_size`, **summarize the middle** while retaining the tail. So the
memory shape is *[stable head] + [LLM summary of the middle] + [recent tail]*. Token/budget
accounting arrives post-hoc as `stats` events (`webhook_router.py:143`); `max_iterations` /
`max_budget_per_task` are forwarded (`settings_models.py:369`) and enforced `[EXTERNAL]`.

### 2e. Sub-agent memory
Three delegation flavors, all coordinated by the control plane:
- **Planning agent → coding agent** hand-off via `PLAN.md` (durable, file-based shared memory).
- **Registered sub-agents** (`get_registered_agent_definitions()`, attached only when
  `enable_sub_agents`, `:1794`).
- **ACP agents** (Claude Code / Codex CLIs) via a separate builder
  (`_build_acp_start_conversation_request`, `:2001`).
Sub-conversations **inherit** sandbox, git params, and model from the parent
(`_inherit_configuration_from_parent`, `:1047`) — so a child shares the *workspace* (filesystem
memory) but has its own event stream. Delegation execution is `[EXTERNAL]`.

### 2f. A unique memory tier: the sandbox filesystem + PLAN.md
Because the agent lives in a **per-conversation sandbox**, the **workspace filesystem itself is
durable working memory** shared across turns and sub-agents. `PLAN.md` is an explicit,
human-readable externalization of the plan. Neither is conversation memory — both are artifacts
the agent re-reads.

---

## 3. "Build me a todo app" — PI

### 3a. Ingestion & decomposition
PI runs **one minimal loop** and, by design, ships **no built-in planner or sub-agents**
(`docs/usage.md:307`). "Build me a todo app" is handled by a single agent iterating
`read/write/edit/bash` until done. Decomposition, if wanted, is an **extension** you install
(e.g. `examples/extensions/subagent` + `scout-and-plan.md`). This is a deliberate philosophical
choice: keep the core a legible loop; make orchestration additive.

### 3b. Where the turn's memory is written
As a **JSONL tree**: each entry has `id` + `parentId` (`session-manager.ts`), appended via
`appendMessage → _appendEntry → _persist` (`appendFileSync`, `:946`). Entry kinds include
messages, model changes, thinking-level changes, **compaction** entries, and **branch summary**
entries. Because it's a *tree*, PI supports in-place **branching / fork / clone** — you can
explore "build the todo app with React" on one branch and "with plain HTML" on another, and each
branch keeps its own memory path.

### 3c. What re-enters the window each turn
`buildSessionContext()` traverses the tree to the active leaf, **applying the compaction cut
(`firstKeptEntryId`) and inlining branch summaries**, then `convertToLlm` maps entries to
provider messages (`messages.ts:148`) and `buildSystemPrompt` prepends the system prompt +
`<project_context>` (AGENTS.md) + a skills XML block (only when the `read` tool is active) + date
+ cwd (`system-prompt.ts`). Skills are surfaced as a **catalog** the model can choose to load
(`formatSkillsForPrompt`), and `disable-model-invocation` skills are `/skill:name`-only.

### 3d. Purge / keep policy — how it forgets (the most explicitly specified of the three)
`compaction/compaction.ts`:
- **Trigger**: `shouldCompact(contextTokens, contextWindow, settings)` = `contextTokens >
  contextWindow − reserveTokens` (`:211`), defaults `reserveTokens=16384`, `keepRecentTokens=20000`
  (`:106`). **Three trigger paths** (`agent-session.ts:_checkCompaction`): *threshold*,
  *overflow* (compact **and retry once**, guarded by `_overflowRecoveryAttempted`), and
  *manual* `/compact`, plus a pre-prompt check.
- **What to keep**: `findCutPoint` (`:377`) walks **backward** accumulating estimated tokens
  until `>= keepRecentTokens`, then snaps to a **valid cut point** — and it **never cuts at a
  `toolResult`** (`findValidCutPoints`, `:325`), so a tool call and its result are never split.
- **What the summary looks like**: a **structured** summary, not free text —
  `## Goal / ## Progress / ## Key Decisions / ## Next Steps / ## Critical Context`
  (`:462`–`:465`). When compacting again, it uses an **iterative `UPDATE` prompt**
  (`UPDATE_SUMMARIZATION_PROMPT`, "UPDATE Next Steps based on what was accomplished", `:480`) to
  *merge* the new work into the previous summary rather than re-summarizing from scratch. Split
  turns get a dedicated `TURN_PREFIX_SUMMARIZATION_PROMPT`.
- Summary budget: `min(0.8 * reserveTokens, model.maxTokens)` (`:560`).

**Net effect for the todo app:** PI keeps the last ~20k tokens verbatim (recent edits, current
errors), compresses everything older into a rolling structured brief that always preserves
*Goal* and *Next Steps*, and never orphans a tool result from its call.

### 3e. Sub-agent memory
None in core. An extension implementing sub-agents would use the SDK's `sendUserMessage` /
custom tools and its own `Session` objects; the isolation/return-channel policy is the
extension's to define. (Contrast: OpenCode bakes recursion + permission-narrowing in; PI leaves
it to you.)

### 3f. A unique memory tier: branch summaries
When you branch away from a path (`branchWithSummary`, `session-manager.ts:1310`), PI writes a
**`branchSummary` entry** capturing what the abandoned path accomplished, and inlines it into the
rebuilt context. This is *memory of roads not taken* — unique among the three.

---

## 4. Side-by-side tables

### 4.1 Memory lifecycle (write → rebuild → evict → summarize → recover)

| Stage | OpenCode | OpenHands | PI |
|---|---|---|---|
| **Write** | SQLite parts (tool part = state machine w/ output) | append-only event JSON (per event) | JSONL tree entry (`id`/`parentId`) |
| **Rebuild window** | `filterCompactedEffect` each turn | `[EXTERNAL]` from event log | `buildSessionContext` (tree walk) |
| **Evict trigger** | `isOverflow` vs `usable()` (buffer 20k) | condenser when events > `max_size=240` `[EXTERNAL]` | `shouldCompact` (>`window−16384`); +overflow +manual |
| **Evict unit** | backward prune of tool-output tokens | middle events (keep first 2 + tail) | entries older than the `keepRecentTokens=20k` cut |
| **Summary shape** | summary message (history filtered behind it) | LLM summary of the middle | **structured** (Goal/Progress/Decisions/Next/Context), iteratively merged |
| **Recover original** | yes — full history stays in SQLite | yes — full event log retained | yes — full JSONL retained; `/tree` to revisit |

### 4.2 What is protected vs discarded on compaction

| | Always protected | First to go |
|---|---|---|
| **OpenCode** | recent ~`PRUNE_PROTECT=40k` tokens of tool output; **all `skill` outputs** | old verbose tool output beyond the protected window |
| **OpenHands** | `keep_first=2` events (original task framing) + recent tail | the middle of the conversation (summarized) |
| **PI** | last `keepRecentTokens=20k`; tool-call↔tool-result pairs never split; the *Goal* section | older turns beyond the cut (compressed into the structured brief) |

### 4.3 Sub-agent memory model

| | Has sub-agents? | Child memory | Returns to parent | Isolation |
|---|---|---|---|---|
| **OpenCode** | yes (`task` tool) | own SQLite session | **final text only** | narrowed permission ruleset; optional background |
| **OpenHands** | yes (planning agent, sub-agent defs, ACP) | own event stream | plan artifact / events | inherits sandbox+model; shares workspace |
| **PI** | no (extension) | extension-defined | extension-defined | extension-defined |

### 4.4 Relevance / retrieval mechanisms (how "keep the relevant info" is achieved)

| Mechanism | OpenCode | OpenHands | PI |
|---|---|---|---|
| Recency window | ✔ (prune-protect) | ✔ (keep tail) | ✔ (keepRecentTokens) |
| Summarization | ✔ | ✔ (LLM condenser) | ✔ (structured, iterative) |
| Skills as triggered instructions | ✔ (`SKILL.md` catalog) | ✔ (**Keyword/Task triggers**) | ✔ (catalog; model-invoked) |
| Instruction files | ✔ (AGENTS.md/CLAUDE.md walk-up) | ✔ (microagents) | ✔ (`<project_context>`) |
| Filesystem-as-memory | ✔ (**per-turn snapshots + revert**) | ✔ (**sandbox workspace**, PLAN.md) | via bash/extension |
| Memory of abandoned paths | — | — | ✔ (**branch summaries**) |
| **Embedding / vector RAG** | ✗ | ✗ | ✗ |

---

## 5. Concrete timeline — "Build me a todo app"

A compressed trace of how memory grows and gets pruned in each.

**OpenCode (single primary agent, SQLite):**
```
turn 1  read cwd/AGENTS.md; todowrite [scaffold, html, js, test]      → parts appended to SQLite
turn 2  write index.html (tool part: pending→running→completed)       → snapshot.track() before
turn 3  write app.js ; shell `python -m http.server` (verbose output) → step-finish patch part
turn 4  edit app.js (add-item bug) ; shell test                       → doom-loop guard watches repeats
...     window nears usable(): isOverflow → SessionCompaction
        → prune backward keeping 40k recent tool tokens + all skill outputs
        → old `http.server` log + turn-2 file dump replaced by a summary message (filtered behind)
turn N  "Done — todo app at ./"                                        → files revertible via snapshots
```

**OpenHands (planning agent → coding agent, event log, sandbox):**
```
provision sandbox (clone/setup) ; PLAN mode → PLAN.md written              [EXTERNAL loop]
event log grows: MessageEvent(plan) → ActionEvent(write) → ObservationEvent(ok) → ...
  every event POSTed to webhook.on_event → saved as one JSON file
events exceed max_size=240 → LLMSummarizingCondenser keeps first 2 + summarizes middle  [EXTERNAL]
sub-agent/ACP may execute part of the plan, inheriting the same sandbox workspace
terminal ConversationStateUpdateEvent → SetTitleCallbackProcessor sets a title (off hot path)
client reads the completed trajectory via REST
```

**PI (single loop, JSONL tree):**
```
turn 1  buildSessionContext(system + AGENTS.md + skills catalog) ; write index.html   → JSONL append
turn 2  write app.js ; edit app.js                                                     → append
turn 3  bash run ; fix                                                                  → append
...     contextTokens > window−16384 → shouldCompact (threshold)
        → findCutPoint keeps last 20k (never splitting a toolResult)
        → structured summary {Goal, Progress, Key Decisions, Next Steps, Critical Context}
        → next compaction UPDATEs that summary in place
(optional) user forks a "React version" branch → branchSummary entry records the HTML attempt
turn N  final answer ; whole tree resumable/branchable on disk
```

---

## 6. Takeaways & honest limitations

1. **Memory is chronological + lossy-compressed, not associative.** All three "keep relevant
   info" via *recency + summarization + artifacts*, never semantic retrieval. If your todo-app
   task needs a detail from 200 turns ago that got summarized away, none of them can *retrieve*
   it back into context on demand — it survives only if it made it into a summary section
   (PI's *Critical Context*), a protected window, a skill, `PLAN.md`, or a file on disk.
2. **Compaction is lossy but the store is not.** The durable transcript always keeps everything
   (SQLite / event log / JSONL); only the *window* is trimmed. Recovery = revisit the store
   (OpenCode `revert`, PI `/tree`, OpenHands trajectory export).
3. **Sub-agents are a memory tool as much as a work tool.** OpenCode's "return only final text"
   and OpenHands' separate event streams are deliberate **context-isolation** moves: they keep a
   child's noisy exploration out of the parent's scarce window. PI leaves this lever unbuilt.
4. **Filesystem is the other memory.** OpenCode snapshots and OpenHands' sandbox workspace treat
   *code on disk* as durable state the agent relies on between turns — a memory tier the
   conversation-only view misses.
5. **The design spectrum** mirrors the projects' philosophies: OpenCode = rich, protected,
   snapshot-backed local memory; OpenHands = event-sourced, cross-process, artifact-driven
   (PLAN.md) memory built for isolation and audit; PI = the most *explicitly specified* and
   most *transparent* compaction (structured, iterative, human-readable JSONL), with everything
   beyond the recency-window-plus-summary left to extensions.

See `04-context-filesystem-prompts.md` for the underlying compaction/prompt mechanics and
`05-orchestration-and-extensibility.md` for the full sub-agent/extensibility detail.
