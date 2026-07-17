# 2. Agent Loop, Reasoning, and State

## 2.1 The execution loop

### OpenCode — `while(true)` with an inner AI-SDK step loop
`SessionPrompt.runLoop` (`packages/opencode/src/session/prompt.ts:1081`) is a literal
`while (true)` (`:1088`). One iteration:
1. Load durable history: `MessageV2.filterCompactedEffect(sessionID)` (`:1092`).
2. Compute the latest turn state `MessageV2.latest(msgs)` (`:1096`, `message-v2.ts:585`).
3. **Stop decision** (`:1106–1130`): break when the last assistant `finish` is set, isn't
   `"tool-calls"`, there are no un-executed tool parts, and `lastUser.id < lastAssistant.id`.
   (Comment notes some providers emit `"stop"` even with tool calls, so it keeps going to
   feed results back.)
4. Handle popped `tasks` (subtask → `handleSubtask`; compaction → `compaction.process`).
5. Create assistant message + `SessionProcessor.create`, resolve tools (`SessionTools.resolve`),
   assemble system prompt, then `handle.process({...})` for **one provider turn** (`:1272`).

The provider turn is `SessionProcessor.process` (`processor.ts:627`): it calls
`llm.stream(streamInput)` **once** (`:640`) and drains the event stream
(`Stream.tap(handleEvent)` + `Stream.takeUntil(needsCompaction)` + `Stream.runDrain`,
`:642–646`), returning `"break" | "continue" | "compact"`.

> **Nuance (verified):** within one `handle.process`, tool execution and multiple
> `step-start`/`step-finish` events are driven **by the Vercel AI SDK** (`streamText`), so a
> single OpenCode loop iteration can contain multiple provider "steps." OpenCode's loop is
> "one `process()` call per iteration," not strictly "one model call."

Concurrency: `SessionPrompt.loop` (`:1343`) → `SessionRunState.ensureRunning`
(`run-state.ts:14`) keeps **one `Runner` per sessionID**, so a second prompt on the same
session joins the running loop instead of starting a competing one.

### OpenHands — the loop is `[EXTERNAL]`; app_server runs a *status* machine
There is **no model/tool iteration in this repo**. What `app_server` runs is a
**conversation-start status machine** (`_start_app_conversation`, `:361`) that ends by POSTing
the assembled request to the agent-server (`:486`). The actual ReAct loop
(`LLM.stream → ActionEvent → confirmation gate → tool exec → ObservationEvent → repeat →
MessageEvent`) runs `[EXTERNAL]` and is surfaced only as a stream of `Event`s POSTed back to
the webhook. Follow-up turns are triggered by proxying user input to
`.../conversations/{id}/events` (`send_message_to_conversation`, `:441`;
`_process_pending_messages`, `:2199`).

### PI — a clean nested loop, model-only
`runLoop` (`packages/agent/src/agent-loop.ts`) is an outer loop (follow-up messages) around
an inner loop (`while hasMoreToolCalls || pendingMessages`). Each inner iteration:
`streamAssistantResponse` (one `streamFn`→`streamSimple` call) → detect
`content[type=="toolCall"]` → `executeToolCalls` → append tool-result messages → `turn_end` →
poll steering. Exactly one provider request per turn (verified: single `llm.stream` per turn).
A `max_iterations`-style guard exists in the condensed harness; the real loop terminates on
"no tool calls" / `terminate` / `shouldStopAfterTurn`.

## 2.2 Planning vs acting

- **OpenCode:** primarily **acting** (ReAct). Optional **plan mode** exists
  (`tool/plan.ts` `PlanExitTool`, `plan-enter.txt`/`plan-exit.txt`) but is gated behind
  `flags.experimentalPlanMode && flags.client === "cli"` (`registry.ts:243`); plans are
  written to `.opencode/plans/*.md`. A `todo` tool (`todowrite`) provides lightweight
  in-context planning.
- **OpenHands:** **first-class planning agent.** `AgentType.PLAN` vs `DEFAULT`
  (`app_conversation_models.py:64`). PLAN mode swaps the system-prompt template to
  `system_prompt_planning.j2`, attaches `get_planning_tools(...)`, injects a
  `PLANNING_AGENT_INSTRUCTION` (`:194`) that tells the planner to hand off to the code agent
  (no execution), and computes a `PLAN.md` path. This is the strongest planning story of the
  three, and it is a **separate agent type**, not a mode flag inside one loop.
- **PI:** **no built-in plan mode** (verified; `docs/usage.md:307`). Planning is expected to be
  composed via an extension (`examples/extensions/subagent` + `scout-and-plan.md`).

## 2.3 Where reasoning happens

In all three, "reasoning" is the LLM; the harness only *shapes* it. The interesting
differences are in how reasoning is *surfaced and steered*:
- **OpenCode:** reasoning is a first-class stream part (`reasoning-start/delta/end`
  `LLMEvent`s → `ReasoningPart`), rendered and persisted. Model-family-specific system prompts
  (`prompt/{anthropic,gpt,gemini,beast,...}.txt`) tune reasoning behavior per model.
- **OpenHands:** reasoning/steering lives in the external agent + the planning agent + a
  **security analyzer** that can itself be LLM-based (`LLMSecurityAnalyzer`) — i.e. a *second*
  reasoning process classifies action risk.
- **PI:** thinking level is an explicit knob (`thinkingLevel`, `ThinkingBudgets`) forwarded to
  providers; reasoning deltas stream like text but there is no separate planning reasoner.

## 2.4 Where state is stored

This is one of the sharpest differentiators.

| | Store | Shape | Source of truth | Resume model |
|---|---|---|---|---|
| **OpenCode** | **SQLite (Drizzle)** — `SessionTable`, `PartTable` (`packages/core/src/**/*.sql.ts`); `Session.Service` CRUD (`session/session.ts`) | Messages of typed **parts**; tool parts are a `pending→running→completed|error` state machine (`schema/session-message.ts:81–119`) | The DB; loop re-reads via `MessageV2.filterCompactedEffect` each turn | Rows persist; V2 adds durable input-admission + crash-resume (`core/session/runner`) |
| **OpenHands** | **Append-only event files** — one JSON per `Event` (`event_service_base.save_event:190`; `filesystem/aws/gcp` backends); path `{user}/v1_conversations/{id.hex}/{event}.json` | **Event sourcing**: `ActionEvent`/`ObservationEvent`/`MessageEvent`/`ConversationStateUpdateEvent` | The event log (rebuildable via `iter_events_for_export`) | Replay the event stream; conversation status persisted separately (SQL start-task table) |
| **PI** | **JSONL tree file** per session (`session-manager.ts`; `_persist` `appendFileSync`, `:946`) | Linear/branching **tree** of entries (`id`/`parentId`); messages + model/thinking/compaction/branch entries | The JSONL file; `buildSessionContext` rebuilds the active path | Re-read the file; branching via `branch`/`branchWithSummary`; fork/clone |

Key insight:
- **OpenCode** picks a **queryable DB** (pagination, multi-observer, per-model filtering).
- **OpenHands** picks **event sourcing** because the producer (agent) and the store
  (control plane) are **different processes** — an append-only event log is the natural
  contract across an HTTP webhook boundary, and it doubles as the audit log / trajectory export.
- **PI** picks a **human-readable JSONL tree** — cheap, branchable (`/tree`, fork, clone),
  inspectable, resumable, zero infra.

## 2.5 Loop termination & guards

- **OpenCode:** stop condition on finish-reason + no pending tool parts (`prompt.ts:1106`);
  a **doom-loop guard** routes 3 identical consecutive tool calls through
  `permission.ask` (`processor.ts:356`). Overflow triggers compaction mid-loop (`:1161`).
- **OpenHands:** termination is `[EXTERNAL]`; `app_server` forwards `max_iterations` /
  `max_budget_per_task` (`settings_models.py:369`) and observes a terminal
  `ConversationStateUpdateEvent`. Budget enforcement is external.
- **PI:** stop on "no tool calls" or all-`terminate` batch or `shouldStopAfterTurn`; overflow
  → compact-and-retry once (`_overflowRecoveryAttempted`); transient errors → auto-retry
  (`_prepareRetry`).
