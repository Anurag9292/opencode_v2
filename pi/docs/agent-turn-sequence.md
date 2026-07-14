# Agent Turn Sequence

This document traces **one complete agent turn** through the `pi` harness, from a
user's input to the final persisted response. Every step cites the exact file,
exported symbol, and the important function call(s) involved.

The harness spans three packages:

| Package | npm name | Role in a turn |
|---------|----------|----------------|
| `pi/packages/coding-agent` | `@earendil-works/pi-coding-agent` | CLI/SDK harness: sessions, instruction loading, system prompt, tools, persistence |
| `pi/packages/agent` | `@earendil-works/pi-agent-core` | Model-agnostic agent loop (`Agent`, `runAgentLoop`) |
| `pi/packages/ai` | `@earendil-works/pi-ai` | Provider streaming (`streamSimple`), tool-arg validation |

Legend:

- **[verified]** — read directly in source during this trace.
- **[unverified]** — inferred, or only partially read (noted where relevant).

Line numbers reflect the source at the time of writing and may drift; treat the
**symbol names** as the stable reference.

---

## Step 0 — Process entry and mode selection

- **File:** `packages/coding-agent/src/main.ts`
- **Symbol:** `main()` (exported; also re-exported from `packages/coding-agent/src/index.ts`)
- The CLI is parsed with `parseArgs` (`src/cli/args.ts`), the initial message is
  assembled by `buildInitialMessage` (`src/cli/initial-message.ts`) and
  `processFileArguments` (`src/cli/file-processor.ts`), and one of three run
  modes is started: `InteractiveMode`, `runPrintMode`, or `runRpcMode`
  (`src/modes/index.ts`). **[verified]**

**Mode differences for "user input → prompt" (Step 1):**

| Mode | File | Call site |
|------|------|-----------|
| Interactive (TUI) | `src/modes/interactive/interactive-mode.ts` | `this.session.prompt(userInput)` (~line 916); initial prompt at ~894; steer/followUp at ~2804 / ~3693 |
| Print (`-p`) | `src/modes/print-mode.ts` | `session.prompt(initialMessage, { images })` (line 122) / `session.prompt(message)` (line 126) |
| RPC (`--mode rpc`) | `src/modes/rpc/rpc-mode.ts` | `.prompt(command.message, { ... })` (~line 398) |

All three converge on the same method: `AgentSession.prompt(text, options)`. **[verified]**

---

## Step 1 — User input reaches the session

- **File:** `packages/coding-agent/src/core/agent-session.ts`
- **Symbol:** `AgentSession.prompt(text, options?: PromptOptions)` (line ~1076)
- This is the single funnel for user input regardless of mode. Preflight order
  (all **[verified]**):
  1. Extension slash-command handling — `_tryExecuteExtensionCommand(text)` (executes immediately, even while streaming).
  2. Input interception — `this._extensionRunner.emitInput(...)` (`input` event; may `handle` or `transform`).
  3. Skill/template expansion — `_expandSkillCommand(text)` then `expandPromptTemplate(...)` (`src/core/prompt-templates.ts`).
  4. If already streaming: queue via `_queueSteer` / `_queueFollowUp` and return.
  5. Model presence + auth validation — `this.model`, `this._modelRegistry.hasConfiguredAuth(this.model)`.
  6. Pre-prompt compaction check — `_checkCompaction(lastAssistant, false)`.
  7. Build the user `AgentMessage` (`{ role: "user", content: [{type:"text",...}, ...images], timestamp }`).
  8. `before_agent_start` hook — `this._extensionRunner.emitBeforeAgentStart(...)` (may append custom messages and/or override the system prompt).
  9. Dispatch — `_runAgentPrompt(messages)`.

---

## Step 2 — Session creation (context for the trace)

Session objects are created once (before the first prompt), but they define the
turn's environment, so they are documented here.

- **File:** `packages/coding-agent/src/core/sdk.ts`
- **Symbol:** `createAgentSession(options)` (exported) — also reachable via
  `createAgentSessionFromServices` (`src/core/agent-session-services.ts`). **[verified]**
- Creates/injects: `AuthStorage.create(...)`, `ModelRegistry.create(...)`,
  `SettingsManager.create(...)`, `SessionManager.create(...)`,
  `DefaultResourceLoader` (then `await resourceLoader.reload()`).
- Restores prior messages when the session file has data:
  `sessionManager.buildSessionContext()` → `agent.state.messages = existingSession.messages`.
- Constructs the low-level `Agent` (see Step 7) wired with `convertToLlm`
  (`convertToLlmWithBlockImages` → `convertToLlm` from `src/core/messages.ts`), a
  provider `streamFn` wrapper, and `transformContext` (→ `runner.emitContext`).
- Finally constructs `new AgentSession({ agent, sessionManager, ... })`.

**Session identity & file (persistence target):**

- **File:** `packages/coding-agent/src/core/session-manager.ts`
- **Symbols:** `SessionManager` class; `SessionManager.getSessionId()` (line 938),
  `getSessionFile()` (line 942). New sessions use `createSessionId()`; the file is
  `join(sessionDir, ${fileTimestamp}_${newSessionId}.jsonl)` (lines ~1352 and ~1520). **[verified]**

---

## Step 3 — Instruction loading (context files, skills, custom prompts)

- **File:** `packages/coding-agent/src/core/resource-loader.ts`
- **Symbol:** `DefaultResourceLoader.reload()` (line ~338) **[verified]**
- Loads, and exposes via getters consumed in Step 4:
  - **Context files** (`AGENTS.md` / `CLAUDE.md`) — `loadProjectContextFiles({cwd, agentDir})` (exported, line 85). Walks global `agentDir` then ancestor dirs up from `cwd`; candidate names in `loadContextFileFromDir` (`AGENTS.md`, `AGENTS.MD`, `CLAUDE.md`, `CLAUDE.MD`). Exposed via `getAgentsFiles()`.
  - **Skills** — `loadSkills(...)` (`src/core/skills.ts`); exposed via `getSkills()`.
  - **Custom system prompt** — `discoverSystemPromptFile()` finds `.pi/SYSTEM.md` (project, trust-gated) or `<agentDir>/SYSTEM.md` (global); exposed via `getSystemPrompt()`.
  - **Appended system prompt** — `discoverAppendSystemPromptFile()` finds `APPEND_SYSTEM.md`; exposed via `getAppendSystemPrompt()`.
  - Extensions/prompts/themes are also resolved here via `DefaultPackageManager`.

---

## Step 4 — System prompt construction

- **File:** `packages/coding-agent/src/core/agent-session.ts`
- **Symbol:** `AgentSession._rebuildSystemPrompt(toolNames)` (line ~983) **[verified]**
- Gathers tool prompt snippets/guidelines, `resourceLoader.getSystemPrompt()`,
  `getAppendSystemPrompt()`, `getSkills().skills`, `getAgentsFiles().agentsFiles`,
  packs them into `BuildSystemPromptOptions`, then calls:
- **File:** `packages/coding-agent/src/core/system-prompt.ts`
- **Symbol:** `buildSystemPrompt(options)` (exported, line 28) **[verified]**
  - Emits the default "expert coding assistant … inside pi" prompt (or uses
    `customPrompt` verbatim), an **Available tools** list (only tools with a
    one-line snippet appear), **Guidelines**, a `<project_context>` block wrapping
    each context file in `<project_instructions path="...">`, a skills section via
    `formatSkillsForPrompt(skills)` (only when the `read` tool is active), and
    finally `Current date` + `Current working directory`.
- The result is stored on `this._baseSystemPrompt` and pushed to the agent via
  `AgentSession.setActiveToolsByName(...)` → `this.agent.state.systemPrompt = this._systemPromptOverride ?? this._baseSystemPrompt`.
- Per-turn refresh: `AgentSession._installAgentNextTurnRefresh()` sets
  `agent.prepareNextTurnWithContext` so each subsequent turn re-applies the
  current system prompt + tools. **[verified]**

---

## Step 5 — Tool registry construction

- **File:** `packages/coding-agent/src/core/agent-session.ts`
- **Symbols:** `AgentSession._buildRuntime(...)` (line ~2490) → `_refreshToolRegistry(...)` **[verified]**
- Built-in tool definitions: `createAllToolDefinitions(cwd, { read, bash })`
  (`src/core/tools/index.ts`), producing `read`, `bash`, `edit`, `write`, `grep`,
  `find`, `ls`.
- Definitions become executable `AgentTool`s via `wrapRegisteredTools(...)`
  (`src/core/extensions/...`) and `wrapToolDefinition` /
  `createToolDefinitionFromAgentTool` (`src/core/tools/tool-definition-wrapper.ts`).
- `setActiveToolsByName([...])` sets `this.agent.state.tools` and rebuilds the
  system prompt. Allowlist/denylist honored via `--tools` / `--exclude-tools`
  (`allowedToolNames` / `excludedToolNames`). **[verified]**

---

## Step 6 — Agent run start (lifecycle events begin)

- **File:** `packages/coding-agent/src/core/agent-session.ts`
- **Symbol:** `AgentSession._runAgentPrompt(messages)` (line ~1023) → `this.agent.prompt(messages)` **[verified]**
- **File:** `packages/agent/src/agent.ts`
- **Symbol:** `Agent.prompt(...)` (line 337) → `runPromptMessages` → `runAgentLoop(...)` (line ~401) **[verified]**
- **File:** `packages/agent/src/agent-loop.ts`
- **Symbol:** `runAgentLoop(prompts, context, config, emit, signal, streamFn)` (line 95)
  - Emits `agent_start`, `turn_start`, then `message_start`/`message_end` for each
    prompt message, then enters `runLoop(...)` (line ~155). **[verified]**
- Events flow back through `Agent.processEvents` (agent.ts:527), which updates
  `agent.state` and then invokes `AgentSession._handleAgentEvent` (the subscriber
  registered in the `AgentSession` constructor via `this.agent.subscribe(...)`).

---

## Step 7 — Model request (context → provider)

- **File:** `packages/agent/src/agent-loop.ts`
- **Symbol:** `streamAssistantResponse(context, config, signal, emit, streamFn)` (line ~281) **[verified]**
  1. `config.transformContext(messages, signal)` — extension `context` hook (→ `runner.emitContext`).
  2. `config.convertToLlm(messages)` — `AgentMessage[] → Message[]`.
     - **File:** `packages/coding-agent/src/core/messages.ts`, **Symbol:** `convertToLlm(messages)` (line 148): maps custom roles (`bashExecution`, `custom`, `branchSummary`, `compactionSummary`) to `user` text and passes through `user`/`assistant`/`toolResult`.
  3. Builds `Context` = `{ systemPrompt, messages: llmMessages, tools }`.
  4. Resolves API key (`config.getApiKey`) and calls `streamFn(model, llmContext, { ...config, apiKey, signal })`.
- **The `streamFn`** is the wrapper defined in `createAgentSession` (`src/core/sdk.ts`, `streamFn:` on the `new Agent({...})` call): **[verified]**
  - `modelRegistry.getApiKeyAndHeaders(model)` for auth.
  - `mergeProviderAttributionHeaders(...)` + `runner.emitBeforeProviderHeaders(...)` (`before_provider_headers` hook).
  - `onPayload` → `runner.emitBeforeProviderRequest(...)` (`before_provider_request` hook).
  - Calls `streamSimple(model, context, { apiKey, headers, timeoutMs, maxRetries, ... })`.
- **File:** `packages/ai/src/compat.ts`, **Symbol:** `streamSimple(...)` (line ~265, dispatch) → per-API impl in `packages/ai/src/api/*.ts` (e.g. `anthropic-messages.ts`, exported `streamSimple`). **[verified via subagent]**

---

## Step 8 — Streamed response

- **File:** `packages/ai/src/api/anthropic-messages.ts` (representative SSE provider) **[verified via subagent; other providers unverified]**
  - Parses SSE with `iterateSseMessages` → `iterateAnthropicEvents`, mapping to the
    unified `AssistantMessageEvent` union (`packages/ai/src/types.ts`, ~line 464):
    `start`, `text_start/delta/end`, `thinking_start/delta/end`,
    `toolcall_start/delta/end`, `done`, `error`.
  - Streaming tool-call arguments accumulate on `block.partialJson` and re-parse via
    `parseStreamingJson` (`packages/ai/src/utils/json-parse.ts`).
  - The stream object is an `AssistantMessageEventStream` (`packages/ai/src/utils/event-stream.ts`, class `EventStream`), whose `.result()` resolves the final `AssistantMessage` on the first `done`/`error` event.
- Back in `streamAssistantResponse` (agent-loop.ts), the provider events are
  translated into **agent events**: `message_start` (on `start`),
  `message_update` (on each delta, carrying `assistantMessageEvent`), and
  `message_end` (on `done`/`error`, using `response.result()`). **[verified]**

---

## Step 9 — Tool-call detection

- **File:** `packages/agent/src/agent-loop.ts`
- **Symbol:** `runLoop(...)` (line ~155) **[verified]**
  - After the assistant message resolves, tool calls are detected with
    `message.content.filter((c) => c.type === "toolCall")` (line ~203).
  - If `message.stopReason === "error" | "aborted"`, the loop emits `turn_end` +
    `agent_end` and returns (no tools).
  - If `message.stopReason === "length"`, all tool calls are failed via
    `failToolCallsFromTruncatedMessage(toolCalls, emit)` (truncated args are unsafe).
  - Otherwise → `executeToolCalls(...)`.

---

## Step 10 — Permission checking

- **File:** `packages/agent/src/agent-loop.ts`
- **Symbol:** `prepareToolCall(currentContext, assistantMessage, toolCall, config, signal)` (line ~602) **[verified]**
  1. Resolves the `AgentTool` by name (missing tool → immediate error result).
  2. `prepareToolCallArguments(tool, toolCall)` (optional `tool.prepareArguments`).
  3. `validateToolArguments(tool, preparedToolCall)` — **File:** `packages/ai/src/utils/validation.ts`, **Symbol:** `validateToolArguments` (line ~278): coerces + validates arguments against the tool's TypeBox/JSON schema; throws on mismatch. **[verified via subagent]**
  4. **Permission gate:** `config.beforeToolCall({ assistantMessage, toolCall, args, context }, signal)`. If it returns `{ block: true, reason }`, the call becomes an immediate error result and is **not** executed.
- **Where the gate is wired:** `packages/coding-agent/src/core/agent-session.ts`,
  `AgentSession._installAgentToolHooks()` (line ~423) sets `agent.beforeToolCall`
  to call `this._extensionRunner.emitToolCall({ type: "tool_call", ... })`
  (`tool_call` extension event). Extensions can block or throw. **[verified]**

> **[unverified / design note]** Pi ships **no built-in permission popups** by
> design (README "Philosophy"). The only permission mechanism is the extension
> `tool_call` hook above; confirmation UIs are provided by extensions. If no
> extension registers a `tool_call` handler, tools run unconditionally after
> argument validation.

---

## Step 11 — Tool execution

- **File:** `packages/agent/src/agent-loop.ts`
- **Symbol:** `executeToolCalls(...)` (line ~413) → `executeToolCallsParallel` (default) or `executeToolCallsSequential` **[verified]**
  - Mode is chosen from `config.toolExecution` (`Agent.toolExecution`, default
    `"parallel"`) or forced sequential if any targeted tool has
    `executionMode: "sequential"`.
  - Per call: emit `tool_execution_start` → `prepareToolCall` (Step 10) →
    `executePreparedToolCall(prepared, signal, emit)` (line ~668): runs
    `prepared.tool.execute(toolCallId, args, signal, onUpdate)`; `onUpdate`
    callbacks emit `tool_execution_update`. Thrown errors become error results
    (`createErrorToolResult`).
  - `finalizeExecutedToolCall(...)` (line ~711) runs the `afterToolCall` hook
    (wired in `AgentSession._installAgentToolHooks` → `runner.emitToolResult`,
    `tool_result` event), which may rewrite content/details/`isError`/`terminate`.
  - `emitToolExecutionEnd(...)` emits `tool_execution_end`.
- Built-in tool implementations live in `packages/coding-agent/src/core/tools/`
  (`read.ts`, `bash.ts`, `edit.ts`, `write.ts`, `grep.ts`, `find.ts`, `ls.ts`). **[verified: directory listing]**

---

## Step 12 — Tool result insertion

- **File:** `packages/agent/src/agent-loop.ts` **[verified]**
  - `createToolResultMessage(finalized)` (line ~774) builds a `ToolResultMessage`
    (`role: "toolResult"`, `toolCallId`, `toolName`, `content`, `details`, `isError`, `timestamp`).
  - `emitToolResultMessage(...)` (line ~789) emits `message_start` + `message_end`
    for the tool result.
  - In `runLoop`, each tool result is pushed into `currentContext.messages` and
    `newMessages` (lines ~218–221), so the next model call sees them. Parallel mode
    preserves **assistant source order** for persisted results even though
    completion events may arrive out of order.

---

## Step 13 — Next model iteration

- **File:** `packages/agent/src/agent-loop.ts`, `runLoop(...)` **[verified]**
  - `hasMoreToolCalls = !executedToolBatch.terminate`; the inner `while` repeats
    (new `turn_start` → `streamAssistantResponse` → tools …) until there are no
    tool calls (or a fully-`terminate` batch).
  - Between turns: `config.prepareNextTurn?.(nextTurnContext)` runs. In the harness
    this is `AgentSession._installAgentNextTurnRefresh`, which reasserts the current
    `systemPrompt`, `tools`, `model`, and `thinkingLevel`. **[verified]**
  - `config.shouldStopAfterTurn?.(...)` can stop gracefully after a turn.
  - Steering: `config.getSteeringMessages()` (→ `Agent` steering queue, drained by
    `AgentSession._queueSteer`) injects queued user messages before the next turn.
  - Follow-ups: after the loop would stop, `config.getFollowUpMessages()` can
    re-enter the outer loop.

---

## Step 14 — Persistence

- **File:** `packages/coding-agent/src/core/agent-session.ts`
- **Symbol:** `AgentSession._handleAgentEvent` (line ~548) **[verified]**
  - On `message_end`: `custom` role → `sessionManager.appendCustomMessageEntry(...)`;
    `user`/`assistant`/`toolResult` → `sessionManager.appendMessage(event.message)`.
  - Tracks `_lastAssistantMessage` and resets the retry counter on a successful
    assistant response.
- **File:** `packages/coding-agent/src/core/session-manager.ts` **[verified]**
  - `appendMessage(message)` (line 988) builds a `SessionMessageEntry` and calls
    `_appendEntry` (line 975) → `_persist(entry)` (line 946), which writes the
    session as **JSONL** (append via `appendFileSync`; first flush writes all
    buffered entries once an assistant message exists).
  - Session entries form a tree (`id` + `parentId`), enabling in-place branching.
  - Model/thinking changes persist separately via `appendModelChange` /
    `appendThinkingLevelChange`.

---

## Step 15 — Final response and settle

- **File:** `packages/agent/src/agent-loop.ts` — `runLoop` emits the terminal
  `agent_end` once both queues are drained (line ~274). **[verified]**
- **File:** `packages/coding-agent/src/core/agent-session.ts` **[verified]**
  - `_runAgentPrompt` `while (await this._handlePostAgentRun())` runs
    `agent.continue()` for: auto-retry (`_isRetryableError` + `_prepareRetry`),
    auto-compaction (`_checkCompaction`), and queued follow-ups
    (`agent.hasQueuedMessages()`).
  - `finally` → clears `_systemPromptOverride`, `_flushPendingBashMessages()`,
    `_emitAgentSettled()` (emits `agent_settled`, resolves `waitForIdle`).
  - The `agent_end` re-emitted to session listeners is augmented with
    `willRetry` (`_willRetryAfterAgentEnd`).
- The active mode's UI/print/RPC layer renders the streamed + final content from
  the `message_update` / `message_end` / `agent_end` events. **[verified]**

---

## Sequence diagram

The same diagram is maintained as a standalone file at
[`agent-turn-sequence.mmd`](./agent-turn-sequence.mmd).

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Mode as Mode (interactive/print/rpc)
    participant Session as AgentSession
    participant Res as DefaultResourceLoader
    participant SP as buildSystemPrompt
    participant Agent as Agent (pi-agent-core)
    participant Loop as runAgentLoop / runLoop
    participant AI as streamFn → streamSimple (pi-ai)
    participant Ext as ExtensionRunner
    participant Tool as AgentTool.execute
    participant SM as SessionManager

    Note over Session,Res: Session creation (createAgentSession) happens once before turn
    Res->>SP: getAgentsFiles / getSkills / getSystemPrompt
    SP-->>Session: base system prompt (agent.state.systemPrompt)

    User->>Mode: types input
    Mode->>Session: prompt(text, options)
    Session->>Ext: emitInput / emitBeforeAgentStart
    Session->>Session: expand skills+templates, validate model+auth
    Session->>Agent: prompt(messages)  [_runAgentPrompt]
    Agent->>Loop: runAgentLoop(...)
    Loop-->>Session: agent_start, turn_start, message_start/end (user)

    loop until no tool calls (terminate)
        Loop->>Loop: convertToLlm(messages) → Context
        Loop->>AI: streamFn(model, context)
        AI->>Ext: before_provider_headers / before_provider_request
        AI-->>Loop: start, text_delta..., toolcall_..., done
        Loop-->>Session: message_start / message_update / message_end (assistant)
        Session->>SM: appendMessage(assistant)

        alt assistant requested tool calls
            Loop->>Loop: detect content[type==toolCall]
            Loop->>AI: validateToolArguments(tool, call)
            Loop->>Ext: beforeToolCall → tool_call hook (permission)
            alt blocked
                Ext-->>Loop: { block:true } → error result
            else allowed
                Loop->>Tool: execute(id, args, signal, onUpdate)
                Tool-->>Loop: result (+tool_execution_update/end)
                Loop->>Ext: afterToolCall → tool_result hook
            end
            Loop-->>Session: message_start/end (toolResult)
            Session->>SM: appendMessage(toolResult)
        end
    end

    Loop-->>Session: agent_end
    Session->>Session: _handlePostAgentRun (retry / compaction / follow-ups)
    Session-->>Mode: agent_settled + final message
    Mode-->>User: renders response
```
