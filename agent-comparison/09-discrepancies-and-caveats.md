# 9. Doc-vs-Implementation Discrepancies & Verification Caveats

Per the methodology, every claim was checked against source. Where the written docs (or the
condensed harnesses, which are *distillations*, not reproductions) diverge from the real core,
it is recorded here. **No hard contradictions were found**; the differences are simplifications
or scope gaps, plus a few doc caveats we could resolve.

## 9.1 OpenCode (`mini-agent` docs vs `packages/opencode/src`)

The `mini-agent` docs are explicit that they *distill* OpenCode without reproducing it. Verified
accurate distillations: "while-loop over a durable transcript, one model call per iteration,
re-read history each turn, persist after every stream event"; "message of typed parts, tool part
is a `pending→running→completed|error` state machine"; "failures are data"; "permission
allow/ask/deny, wildcard, last-match-wins, default ask"; "EventBus publish-only; subscribers
additive"; "store is the single source of truth." The stage-list of *excluded* features
(compaction, snapshots, Effect runtime, MCP/plugins/skills/LSP, provider catalog, sub-agents)
all exist in real OpenCode exactly where the doc predicts.

**Nuances / simplifications to flag:**
1. **"Exactly one model call per iteration"** — true per *turn*, but OpenCode-V1 delegates the
   inner tool-call/step loop to the **Vercel AI SDK** (`streamText` with multiple
   `step-start/step-finish`), so a single `handle.process` can span multiple provider steps
   (`processor.ts`). The mini-agent's one-call-per-loop is a simplification.
2. **Two cores, not one.** Real OpenCode has both V1 (`SessionPrompt`) and a durable V2
   (`packages/core/src/session/runner/llm.ts`) with input-admission/run-coordinator/crash-resume
   — i.e. the "durable execution" the doc lists as *excluded* is partially built.
3. **Storage:** mini-agent's own impl uses JSON files and *notes* SQLite as the production
   choice; real OpenCode indeed uses **SQLite/Drizzle** — a version gap, not a contradiction.
4. **Tool parallelism:** mini-agent runs a simple `for call in tool_calls` sequential loop; real
   OpenCode lets the AI SDK schedule tools (V1) or runs a `FiberSet` (V2). Neither is a plain
   sequential loop.
5. **Streaming events:** mini-agent's `TextDelta|ToolCallRequest|Finish` is a reduced form of
   OpenCode's richer `LLMEvent` (reasoning-*, tool-input-*, step-*, provider-error, patch/snapshot).

## 9.2 OpenHands (`docs/*` + `agent_harness` vs `app_server`)

The OpenHands docs (`agent-turn-sequence.md`, `core-module-map.md`) are **accurate and
well-cited**; the central control-plane/external-loop boundary matches the code. Resolutions and
notes:

1. **Resolved caveat:** `core-module-map.md` said the default binding of `AppConversationService`
   to `LiveStatusAppConversationService` was *inferred*. Verified: it is bound in
   `config.py:405` (`LiveStatusAppConversationServiceInjector`). The caveat can be dropped.
2. **Verified line refs:** `_consume_remaining` (`:1659`) and the streaming start route (`:1022`)
   in `app_conversation_router.py` are correct.
3. **`event/event_store.py` is empty/unused** — consistent with the docs' caveat; nothing in the
   traced path imports it (intent still unverified).
4. **Harness simplification (important):** the `agent_harness` puts a `PermissionPolicy.check`
   *inside the loop*. In real OpenHands the control plane only **selects** the policy
   (`_select_confirmation_policy`) and **ships** it to the agent-server
   (`_set_security_analyzer_from_settings`); **enforcement is `[EXTERNAL]`**. The harness's
   in-loop gate is the agent-server's analogue, not `app_server`'s.
5. **Docs under-emphasize a second dispatch path:** the **ACP agent** builder
   (`_build_acp_start_conversation_request`, `:2001`) and `switch_profile`/`switch_acp_model`
   proxy routes are additional `[EXTERNAL]`-dispatch surfaces. Not wrong — an omission.
6. **The hard caveat stands:** everything inside `openhands.sdk` / `openhands.agent_server`
   (system-prompt rendering, LLM streaming, tool detection/execution, confirmation enforcement,
   condenser execution) is **not in this repo** and is `(unverified)` here. All such claims are
   tagged `[EXTERNAL]`.

## 9.3 PI (`pi/docs/*` + `pi/agent_harness` vs `pi/packages`)

The PI docs and harness (authored alongside this analysis) match the source. Verifications and
clarifications:

1. **Edit is string-replace, not patch-apply.** Patch/diff (`generateUnifiedPatch`,
   `generateDiffString`) live in `tools/edit-diff.ts` and are used for **display**; the edit
   itself is exact+fuzzy string replacement. (Clarifies any impression that `edit.ts` applies a
   patch.)
2. **No `packages/opencode` in PI.** PI's permission logic is in `packages/agent` +
   `packages/coding-agent`; there is **no built-in permission gate** beyond the extension
   `tool_call` hook (verified `runner.ts:emitToolCall`, `agent-session.ts:_installAgentToolHooks`).
3. **No MCP source** anywhere in PI (verified) — only doc mentions saying "No MCP by design."
4. **Compaction has three trigger paths**, not two: threshold, overflow (with a one-shot
   compact-and-retry via `_overflowRecoveryAttempted`), and manual `/compact`, plus a pre-prompt
   check (`agent-session.ts:_checkCompaction`, `:1160`).
5. **Bash has no persistent shell** and **no default timeout**: a fresh `child_process.spawn`
   per call (`tools/bash.ts:createLocalBashOperations`), `killProcessTree` on abort/timeout.
6. **Runtime is plain async, not Effect** (verified: zero `effect` imports in `packages/agent`
   and `packages/coding-agent`). The repo-root `AGENTS.md` Effect/Schema conventions apply to the
   broader monorepo, not these pi packages.
7. **`streamSimple` dispatch** is at `packages/ai/src/compat.ts:265` (verified exact).

## 9.4 Cross-cutting verification caveats

- **OpenHands internal loop is unverifiable from this repo.** Any statement about *how*
  OpenHands streams, detects tool calls, enforces confirmation, or renders its system prompt is
  `[EXTERNAL]` and based on the request/response contract app_server uses, not on reading the
  agent-server. Treat those as interface-level, not implementation-level, claims.
- **OpenCode has two cores**; statements about "the loop" default to the V1 production path
  (`SessionPrompt`) unless V2 (`SessionRunner`) is named. Feature availability can differ between
  them (e.g. genuine concurrent tool fibers exist in V2).
- **Line numbers drift.** Symbol names are the stable reference; treat `:NNN` as approximate.
- **The condensed harnesses are teaching reimplementations**, not the shipping code. They are
  cited to illustrate the *intended* flow; the authoritative behavior is always the core
  implementation cited alongside.
