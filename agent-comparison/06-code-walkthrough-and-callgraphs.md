# 6. Code Walkthrough & Call Graphs

For each project: the most important files (why), then the call graph from user request to
final response. Citations are `file:symbol` (line where known).

## 6.1 OpenCode

### Most important files
| File | Why it matters |
|---|---|
| `packages/opencode/src/session/prompt.ts` | The V1 agent turn loop (`runLoop`, `:1081`); user-message creation; subtask/command/shell orchestration. **Read first.** |
| `packages/opencode/src/session/processor.ts` | One provider turn (`SessionProcessor.process`, `:627`): consumes `LLMEvent`s, drives the part state machine, settles tool calls, signals compaction. |
| `packages/opencode/src/session/llm.ts` | Provider seam: AI SDK `streamText` (`:280`) → normalized `LLMEvent` (`toLLMEvents`, `:376`); optional native runtime. |
| `packages/opencode/src/session/tools.ts` | Binds registry + MCP tools into AI-SDK tool objects with permission + plugin hooks (`resolve`, `:41`). |
| `packages/opencode/src/tool/tool.ts` + `tool/registry.ts` | Tool contract (`Def`, `define`, schema decode + truncate) and discovery/registration + per-model filtering. |
| `packages/opencode/src/permission/index.ts` | allow/ask/deny wildcard engine (`evaluate`, `:28`; `ask`, `:67`). |
| `packages/opencode/src/snapshot/index.ts` | Shadow-git per-turn snapshots; patch/diff/restore/revert. |
| `packages/opencode/src/session/session.ts` | SQLite/Drizzle session+message+part CRUD (source of truth). |
| `packages/opencode/src/event-v2-bridge.ts` + `bus/global.ts` | Event publish boundary (EventV2 → GlobalBus + durable sync). |
| `packages/core/src/session/runner/llm.ts` | V2 durable runner (one `llm.stream` per turn, FiberSet tool settlement, crash-resume). |
| `packages/opencode/src/session/system.ts` + `instruction.ts` | System-prompt assembly (per-model `.txt`, `<env>`, AGENTS.md/CLAUDE.md). |

### Call graph (V1, HTTP)
```
client POST → server/.../handlers/session.ts:prompt (:295)
 → SessionPrompt.prompt (session/prompt.ts:1052)
   → createUserMessage (:635)                      # persist user msg, resolve file/agent parts
   → loop({sessionID}) (:1343) → SessionRunState.ensureRunning (run-state.ts:14)
     → runLoop (:1081)  [while(true)]
        ├ MessageV2.filterCompactedEffect          # load durable history (SQLite)
        ├ MessageV2.latest                         # stop-decision inputs
        ├ SessionProcessor.create                  # assistant msg + snapshot.track()
        ├ SessionTools.resolve                     # tools = builtin ∪ mcp ∪ plugin
        ├ SystemPrompt.environment/skills/mcp + Instruction.system  # AGENTS.md, <env>
        └ handle.process(streamInput) (processor.ts:627)
             └ LLM.stream (llm.ts:280 streamText) → toLLMEvents → handleEvent
                  · text/reasoning deltas → parts (updatePartDelta)
                  · tool-call → running → SessionTools execute (AI SDK) → permission.ask → completed/error
             returns "break" | "continue" | "compact"
        → loop until stop (§2) → return lastAssistant(sessionID)
 events → EventV2Bridge → GlobalBus → SSE (server/event.ts) → client
```

## 6.2 OpenHands

### Most important files
| File | Why it matters |
|---|---|
| `app_conversation/live_status_app_conversation_service.py` | The orchestrator: status machine + `_build_start_conversation_request_for_user` (`:1630`) + dispatch `POST /api/conversations` (`:486`). |
| `app_conversation/app_conversation_service_base.py` | Clone/init (`:342`), setup script (`:538`), git hooks (`:557`), condenser (`:614`), confirmation policy (`:677`), security analyzer (`:650/:690`). |
| `app_conversation/app_conversation_router.py` | REST surface: `start_app_conversation` (`:365`), `send_message_to_conversation` (`:441`, thin proxy to `/events`). |
| `event_callback/webhook_router.py` | Inbound push webhook `on_event` (`:468`): persist + reconcile status + fan out callbacks; `get_secret` (`:553`). |
| `event/event_service_base.py` (+ backends) | Append-only, per-event JSON storage (`save_event`, `:190`; path `get_conversation_path`, `:66`). |
| `sandbox/docker_sandbox_service.py` + `sandbox/sandbox_service.py` | Runs the agent-server container; injects `OH_WEBHOOKS_0_BASE_URL` (`:419`) + session key. |
| `settings/settings_models.py` | Source of LLM/agent/condenser/`confirmation_mode`/`security_analyzer`/skills config. |
| `app_conversation/skill_loader.py` + `hook_loader.py` | Proxy to agent-server `/api/skills`, `/api/hooks`; marketplace org config. |
| `mcp/mcp_router.py` | Self-hosted MCP (Tavily proxy) keeping the key out of the sandbox. |
| `config.py` | DI injectors — chooses event backend, sandbox impl, service bindings. |

### Call graph
```
client POST /api/v1/app-conversations
 → app_conversation_router.start_app_conversation (:365)      # return first status; background the rest
   → LiveStatusAppConversationService.start_app_conversation (:352)
     → _start_app_conversation (:361)  [status machine]
        ├ _wait_for_sandbox_start (:888) → sandbox_service.start_sandbox   # inject OH_WEBHOOKS_0_BASE_URL
        ├ run_setup_scripts (:269) → clone_or_init_git_repo / setup.sh / pre-commit / skills
        ├ _build_start_conversation_request_for_user (:1630)
        │    ├ _configure_llm (:1215)  [stream=True]
        │    ├ get_default_tools / get_planning_tools + MCP + secrets + system_message_suffix
        │    ├ _select_confirmation_policy (service_base:677)
        │    └ create_agent() / create_request()  [EXTERNAL SDK]
        └ POST {agent_server}/api/conversations (:486)  ── DISPATCH (EXTERNAL runs the loop) ──▶

[EXTERNAL agent-server: system prompt → LLM.stream → ActionEvent → confirm gate → tool exec → ObservationEvent → MessageEvent]
 └ POST /api/v1/webhooks/events/{id} → webhook_router.on_event (:468)
      ├ asyncio.gather(event_service.save_event(...)) (:480)        # append-only JSON
      ├ reconcile stats / execution_status / switch_llm (:486–512)
      └ background_tasks: _run_callbacks_in_bg_and_close (:583) → SetTitleCallbackProcessor

client reads: event_router (REST search/count/batch-get)  |  live UI: agent-server WebSocket (conversation_url)
follow-up input: send_message_to_conversation (:441) / _process_pending_messages (:2199) → POST /events
```

## 6.3 PI

### Most important files
| File | Why it matters |
|---|---|
| `packages/agent/src/agent-loop.ts` | The core loop: `runLoop`, `streamAssistantResponse`, `executeToolCalls`, `prepareToolCall`. **Read first.** |
| `packages/agent/src/agent.ts` | `Agent` class: state, `subscribe`/`processEvents`, steering/follow-up queues. |
| `packages/coding-agent/src/core/agent-session.ts` | `AgentSession`: persistence bridge (`_handleAgentEvent`), tool hooks (`_installAgentToolHooks`), compaction, retry, per-turn refresh. |
| `packages/coding-agent/src/core/sdk.ts` | `createAgentSession` factory + provider `streamFn` wrapper (auth, headers, hooks). |
| `packages/coding-agent/src/core/session-manager.ts` | JSONL tree persistence (`appendMessage`→`_appendEntry`→`_persist`), branching. |
| `packages/coding-agent/src/core/system-prompt.ts` + `messages.ts` | `buildSystemPrompt` + `convertToLlm`. |
| `packages/coding-agent/src/core/extensions/{runner,types,loader}.ts` | The extension API — PI's core extensibility. |
| `packages/coding-agent/src/core/compaction/compaction.ts` | `shouldCompact`, `findCutPoint`, `generateSummary`, `compact`. |
| `packages/ai/src/compat.ts` | `streamSimple` provider dispatch (SSE/websocket, 35 catalogs). |
| `packages/coding-agent/src/core/tools/{edit,bash,...}.ts` + `edit-diff.ts` | Built-in tools; fuzzy edit + display diff; fresh-spawn bash. |

### Call graph
```
mode (interactive/print/rpc) → AgentSession.prompt (agent-session.ts:1076)
 ├ _tryExecuteExtensionCommand / emitInput / _expandSkillCommand / expandPromptTemplate
 ├ validate model + auth ; _checkCompaction(lastAssistant, false)
 ├ build user message ; emitBeforeAgentStart (may append msgs / override system prompt)
 └ _runAgentPrompt → Agent.prompt (agent.ts:337) → runAgentLoop (agent-loop.ts:95)
      → runLoop (:155)  [outer: follow-ups; inner: tool calls]
         ├ transformContext (extension `context` hook)
         ├ convertToLlm (messages.ts:148) → Context{systemPrompt, messages, tools}
         ├ streamFn (sdk.ts) → streamSimple (ai/compat.ts:265)   # SSE/ws; auth+headers hooks
         │    → streamAssistantResponse: message_start/update/end
         ├ detect content[type=="toolCall"]  (fail all if stopReason=="length")
         ├ executeToolCalls → prepareToolCall (validateToolArguments + beforeToolCall gate)
         │    → executePreparedToolCall (tool.execute + onUpdate) → afterToolCall
         │    → tool-result messages (message_start/end)
         └ turn_end ; poll getSteeringMessages ; loop
      → agent_end
 persistence: AgentSession._handleAgentEvent on message_end → SessionManager.appendMessage (JSONL)
 post-run: _handlePostAgentRun → retry (_prepareRetry) / compaction (_checkCompaction) / follow-ups
```

## 6.4 The three call graphs side by side

- **OpenCode:** one process, one call graph, DB-backed, event bus → SSE. Complexity is *depth*
  (Effect layers, two cores, snapshots, LSP).
- **OpenHands:** the call graph **crosses a process boundary twice** (dispatch out, webhook in).
  Complexity is *distribution* (sandbox, status machine, event sourcing, callbacks).
- **PI:** one process, the shortest call graph, JSONL-backed, in-process subscribers. Complexity
  is *pushed to the edges* (extensions).
