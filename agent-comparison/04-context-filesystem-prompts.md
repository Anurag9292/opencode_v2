# 4. Context/Memory, Filesystem/Git, Prompts, Streaming/UI

## 4.1 Context management, memory, token management, compression

### OpenCode
- **History** re-read from **SQLite** each turn (`MessageV2.filterCompactedEffect`,
  `message-v2.ts:521` hides compacted history behind a summary).
- **Context assembly** (`prompt.ts:1257`): `Effect.all([sys.skills, sys.environment,
  instruction.system, sys.mcp, MessageV2.toModelMessagesEffect])`. Env block `<env>` (cwd,
  worktree, git, platform, date, model) via `SystemPrompt.environment` (`system.ts:60`);
  `AGENTS.md`/`CLAUDE.md` via `Instruction.Service` (`instruction.ts`), walking upward and
  attaching instruction files near read files.
- **Token counting:** heuristic `util/token.ts` (`Token`/`estimate`).
- **Compaction:** overflow detection `session/overflow.ts:isOverflow` (`:22`) vs `usable()`
  (context window minus `COMPACTION_BUFFER=20_000`); triggered in the loop (`prompt.ts:1161`)
  and on `step-finish`/`ContextOverflowError`. `SessionCompaction.Service` summarizes and
  prunes (`PRUNE_MINIMUM=20_000`, `PRUNE_PROTECT=40_000`, protects `skill` outputs).

### OpenHands
- **History = the event stream** (rebuild via `iter_events_for_export`).
- **Condenser configured here, executed `[EXTERNAL]`:** `_create_condenser`
  (`app_conversation_service_base.py:614`) builds an `[EXTERNAL]` `LLMSummarizingCondenser`
  (defaults `max_size=240, keep_first=2`), separate `usage_id` (`condenser`/`planning_condenser`),
  optional `condenser_max_size`. Actual condensation runs in the agent-server.
- **Token/budget:** no counting in `app_server`; it forwards `max_iterations`/
  `max_budget_per_task` and receives cost/token `stats` events post-hoc (`webhook_router.py:143`).

### PI
- **History** from the JSONL tree; `buildSessionContext` rebuilds the active path applying the
  compaction cut and branch summaries.
- **Token counting:** `ai/src/utils/estimate.ts` (chars/4, adds system-prompt + tool-schema
  tokens, image≈4800 chars), prefers real provider `usage.totalTokens` when available.
- **Compaction:** `compaction/compaction.ts` — `shouldCompact` (threshold: `> contextWindow -
  reserveTokens`, defaults `reserveTokens=16384, keepRecentTokens=20000`), `findCutPoint`
  (never cuts at a `toolResult`), `generateSummary` (structured
  `## Goal / Progress / Key Decisions / Next Steps / Critical Context`), iterative
  `UPDATE_SUMMARIZATION_PROMPT` to merge with a previous summary. Three trigger paths:
  **threshold**, **overflow (compact-and-retry once)**, and **manual `/compact`**, plus a
  pre-prompt check (`agent-session.ts:_checkCompaction`).

**Comparison:** OpenCode and PI both do *summarize-and-cut with a protected recent window*, in
the same process as the loop. OpenHands *configures* an LLM condenser but runs it externally.
PI's compaction is the most explicitly specified (structured summary schema, 3 trigger paths).

## 4.2 Filesystem interaction, patch generation, git

### Reading / editing
- **OpenCode:** `tool/read.ts`, `tool/edit.ts` (`EditTool`) — string-replace edits with a
  `diff.createTwoFilesPatch` diff (`edit.ts:101`), per-file `Semaphore` lock, external-dir
  guard, permission ask, **formatter + LSP diagnostics** integration; `tool/write.ts` full
  write; `tool/apply_patch.ts` is the patch-format editor selected for GPT-5-class models.
- **PI:** `tools/edit.ts` — **multi-edit exact + fuzzy string replacement** (not patch-apply):
  `applyEditsToNormalizedContent` (`edit-diff.ts:304`) matches each edit against the original
  (exact, then NFKC/smart-quote fuzzy `fuzzyFindText`), enforces uniqueness + non-overlap,
  preserves line endings/BOM; **patch/diff generated for display** via `generateUnifiedPatch`
  / `generateDiffString` (`edit-diff.ts:369/380`). File writes serialized by
  `withFileMutationQueue` (per-realpath promise chain).
- **OpenHands:** file editing is `[EXTERNAL]` (in `openhands.tools`); `app_server` only does
  **repo-level** filesystem ops during setup (clone, setup.sh, hooks) via `AsyncRemoteWorkspace`.

### Patch generation
- **OpenCode:** real diffs for edits; dedicated `apply_patch` tool for patch-native models;
  per-turn **`patch` message part** computed from snapshot deltas.
- **PI:** unified-diff generated for *display only*; edits are string replacements.
- **OpenHands:** `[EXTERNAL]`.

### Git integration
- **OpenCode:** VCS detection (`ctx.project.vcs`); **per-turn shadow-git snapshots**
  (`snapshot/index.ts`): a separate git dir per project captures a `write-tree` hash before
  each turn (`processor.ts:102`), emits `step-start` parts carrying the snapshot, computes a
  `patch` part of changed files on `step-finish`, and supports `restore`/`revert`
  (`session/revert.ts`). This is genuine time-travel over file state.
- **OpenHands:** **git is a platform concern.** `clone_or_init_git_repo` (`:342`, authenticated
  clone, `--depth 1` default), `maybe_run_setup_script` (`.openhands/setup.sh`),
  `maybe_setup_git_hooks` (uploads a `pre-commit.sh` shim, preserves prior hook),
  provider integrations (`integrations/{github,gitlab,bitbucket,azure_devops,forgejo}`),
  branch-name validation. Credentials via scoped JWT `LookupSecret`.
- **PI:** no built-in git tool; git is done through `bash` or an extension.

**Comparison:** OpenCode has the most sophisticated *local* file-safety story
(**snapshots + revert + LSP-aware edits**). OpenHands has the most sophisticated *repo/platform*
git story (clone/auth/hooks/providers) but delegates actual file edits to the sandboxed agent.
PI keeps editing minimal (fuzzy string replace) and pushes git to bash/extensions.

## 4.3 Prompt architecture

| | System prompt | Tool prompts | Dynamic construction |
|---|---|---|---|
| **OpenCode** | Model-family `.txt` files `prompt/{anthropic,default,beast,gemini,gpt,codex,kimi,meta,trinity}.txt`, selected by model id (`system.ts:SystemPrompt.provider`, `:27`) | Per-tool `.txt` co-located (`edit.txt`, `read.txt`, …), imported into each tool | Final array = `[...environment, ...instructions(AGENTS.md), mcp?, skills?]` + `MAX_STEPS_PROMPT` + structured-output prompt; task tool description augmented with live sub-agent list |
| **OpenHands** | Rendered `[EXTERNAL]` from a **Jinja template** (`system_prompt_planning.j2` literal is the only local trace); app_server supplies **inputs only** | `[EXTERNAL]` | app_server assembles `system_message_suffix` (planning boundary, `<HOST>` block, shallow-clone context), selects the template filename + kwargs (`cli_mode`, `plan_structure`), attaches skills/hooks to `AgentContext` |
| **PI** | One base prompt in code (`system-prompt.ts:buildSystemPrompt`) or a custom `.pi/SYSTEM.md`; `APPEND_SYSTEM.md` to append | Tools appear as a one-line "Available tools" list (only tools with a snippet); guidelines list | `<project_context>` wraps `AGENTS.md`/`CLAUDE.md`; skills XML (`formatSkillsForPrompt`) only when `read` is active; date + cwd appended; extensions can override via `before_agent_start` |

**Comparison:** OpenCode has the richest prompt engineering (**per-model prompt variants** +
per-tool prompt files). OpenHands centralizes prompt *rendering* in a Jinja template inside the
SDK and keeps the control plane to assembling inputs (clean separation, but the actual prompt
isn't in this repo). PI keeps a single small prompt with file-based overrides and an extension
hook — consistent with its minimal philosophy.

## 4.4 Streaming & UI, events, progress, interruptibility

| | Streaming | Event architecture | Interruptibility |
|---|---|---|---|
| **OpenCode** | Vercel AI SDK `streamText` → normalized `LLMEvent` union (text/reasoning/tool-input/tool-call/tool-result/step/finish/provider-error) | **Two layers:** in-process `GlobalBus` (EventEmitter) + canonical **EventV2** via `event-v2-bridge.ts` (annotates `Location`, forwards + a durable `sync` payload); **SSE** to clients (`server/event.ts`) | `Tool.Context.abort`; per-session runner cancel (`cancel` endpoint) |
| **OpenHands** | Model streaming is `[EXTERNAL]` (`stream=True` forced in `_configure_llm`); **no SSE/WebSocket in app_server** — clients read events via REST or connect to the **agent-server's own WebSocket** (`conversation_url`) | **Event sourcing over a webhook**: agent-server POSTs `Event`s to `on_event`; callbacks fan out off the hot path (`background_tasks`) | External loop; pause/resume/delete lifecycle via `on_conversation_update` |
| **PI** | `streamSimple` provider events (SSE default; websocket for some) → `streamAssistantResponse` → `message_start/update/end` → `Agent.processEvents` → `AgentSession` listeners → TUI | In-process `EventBus`/subscriber; `Agent.subscribe` awaited listeners in order; extension runner mirrors events | `AbortSignal` threaded everywhere; `abort()`/`waitForIdle`; **steering** (interrupt mid-run) + **follow-up** queues (`agent.steer/followUp`) |

**Progress reporting:** OpenCode streams tool state transitions + live shell output into part
metadata; OpenHands surfaces progress as the event stream + status machine + title callback;
PI streams deltas and tool-execution updates, with steering messages injected between turns.

**Comparison:** OpenCode and PI stream **in-process** with an event bus and SSE/TUI. OpenHands
streams **across processes** — the control plane deliberately holds no live socket to the
client for events; it persists what the agent pushes and lets the client read REST or talk to
the agent-server directly. PI is unique in **steering** (interrupt-and-redirect while tools run)
and **follow-up** queues as a first-class UX primitive.
