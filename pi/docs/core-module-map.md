# Core Module Map

A responsibility map of the `pi` harness modules touched by an agent turn. Paths
are relative to the repo root. Symbols are the stable reference; line numbers may
drift. Items marked **[unverified]** were not fully read during this pass.

## Package layout

| Package | npm name | Responsibility |
|---------|----------|----------------|
| `pi/packages/coding-agent` | `@earendil-works/pi-coding-agent` | CLI + SDK harness: modes, sessions, resources, system prompt, tools, persistence, extensions |
| `pi/packages/agent` | `@earendil-works/pi-agent-core` | Model-agnostic agent loop, tool orchestration, lifecycle events |
| `pi/packages/ai` | `@earendil-works/pi-ai` | Providers, `streamSimple`, event stream, tool-arg validation, retry/overflow helpers |
| `pi/packages/tui` | `@earendil-works/pi-tui` | Terminal UI primitives (interactive mode rendering) |
| `pi/packages/orchestrator` | — | Process supervision / RPC process management **[unverified]** |

## Entry & CLI (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/main.ts` | `main()` | CLI parse, mode dispatch |
| `src/cli/args.ts` | `parseArgs`, `Args` | Argument parsing |
| `src/cli/initial-message.ts` | `buildInitialMessage` | Compose first prompt |
| `src/cli/file-processor.ts` | `processFileArguments` | `@file` inclusion |
| `src/index.ts` | package exports | Public SDK surface |

## Run modes (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/modes/interactive/interactive-mode.ts` | `InteractiveMode` | TUI loop; calls `session.prompt(...)` |
| `src/modes/print-mode.ts` | `runPrintMode` | One-shot `-p` output |
| `src/modes/rpc/rpc-mode.ts` | `runRpcMode` | JSONL RPC over stdio |
| `src/modes/index.ts` | mode re-exports | — |

## Session orchestration (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/sdk.ts` | `createAgentSession`, `createCodingTools` | Wires Agent + services; builds `streamFn` |
| `src/core/agent-session-services.ts` | `createAgentSessionServices`, `createAgentSessionFromServices` | cwd-bound service bundle |
| `src/core/agent-session-runtime.ts` | `AgentSessionRuntime`, `createAgentSessionRuntime` | Multi-session runtime **[unverified]** |
| `src/core/agent-session.ts` | `AgentSession`, `.prompt`, `_runAgentPrompt`, `_handleAgentEvent`, `_installAgentToolHooks`, `_installAgentNextTurnRefresh`, `_rebuildSystemPrompt`, `_buildRuntime`, `_checkCompaction`, `_prepareRetry` | Central harness: lifecycle, persistence bridge, tools, compaction, retry |

## Agent core (agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/agent.ts` | `Agent`, `AgentOptions`, `prompt`, `continue`, `subscribe`, `processEvents`, `steer`, `followUp` | Stateful wrapper, event fan-out, queues |
| `src/agent-loop.ts` | `runAgentLoop`, `runAgentLoopContinue`, `runLoop`, `streamAssistantResponse`, `executeToolCalls`, `prepareToolCall`, `executePreparedToolCall`, `finalizeExecutedToolCall`, `createToolResultMessage` | The turn loop, tool orchestration |
| `src/types.ts` | `AgentContext`, `AgentEvent`, `AgentLoopConfig`, `AgentMessage`, `AgentTool`, `AgentToolCall`, `AgentToolResult`, `StreamFn` | Core types |
| `src/index.ts` | re-exports | Public surface |

## Instruction & resource loading (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/resource-loader.ts` | `DefaultResourceLoader`, `reload`, `loadProjectContextFiles`, `discoverSystemPromptFile`, `discoverAppendSystemPromptFile`, `getAgentsFiles/getSkills/getSystemPrompt/getAppendSystemPrompt` | AGENTS.md/CLAUDE.md, SYSTEM.md, skills, prompts, themes, extensions |
| `src/core/skills.ts` | `loadSkills`, `formatSkillsForPrompt`, `Skill` | Skill discovery + prompt formatting |
| `src/core/prompt-templates.ts` | `loadPromptTemplates`, `expandPromptTemplate`, `PromptTemplate` | `/template` expansion |
| `src/core/package-manager.ts` | `DefaultPackageManager` | Pi package resolution |

## System prompt (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/system-prompt.ts` | `buildSystemPrompt`, `BuildSystemPromptOptions` | Assembles final system prompt |

## Message conversion (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/messages.ts` | `convertToLlm`, `BashExecutionMessage`, `CustomMessage`, `CompactionSummaryMessage`, `BranchSummaryMessage`, `bashExecutionToText` | Custom `AgentMessage` types → LLM `Message[]` |

## Tools (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/tools/index.ts` | `createAllToolDefinitions`, `createCodingTools`, `createReadOnlyTools`, per-tool factories | Built-in tool definitions |
| `src/core/tools/tool-definition-wrapper.ts` | `wrapToolDefinition`, `wrapToolDefinitions`, `createToolDefinitionFromAgentTool` | `ToolDefinition` ↔ `AgentTool` |
| `src/core/tools/{read,bash,edit,write,grep,find,ls}.ts` | per-tool `create*ToolDefinition` | Implementations |
| `src/core/tools/file-mutation-queue.ts` | `withFileMutationQueue` | Serialize file writes |

## Persistence (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/session-manager.ts` | `SessionManager`, `appendMessage`, `appendCustomMessageEntry`, `appendModelChange`, `appendThinkingLevelChange`, `appendCompaction`, `_appendEntry`, `_persist`, `buildSessionContext`, `getSessionId/getSessionFile` | JSONL tree persistence + context rebuild |
| `src/migrations.ts` | `runMigrations` | Session/format migrations |

## Config & services (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/settings-manager.ts` | `SettingsManager` | Global/project settings, retry/compaction/queue modes |
| `src/core/auth-storage.ts` | `AuthStorage` | Credential storage |
| `src/core/model-registry.ts` | `ModelRegistry`, `getApiKeyAndHeaders`, `hasConfiguredAuth`, `isUsingOAuth` | Model discovery + auth resolution |
| `src/core/model-resolver.ts` | `findInitialModel`, `resolveCliModel` | Model selection |
| `src/core/compaction/index.ts` | `compact`, `shouldCompact`, `prepareCompaction`, `generateSummary` | Context compaction |

## Extensions (coding-agent)

| File | Key symbols | Role |
|------|-------------|------|
| `src/core/extensions/index.ts` | `ExtensionRunner`, `ExtensionAPI`, `ToolDefinition`, event types | Extension host |
| `src/core/extensions/runner.ts` | `ExtensionRunner.emit*`, `emitToolCall`, `emitToolResult`, `emitInput`, `emitBeforeAgentStart`, `emitBeforeProviderHeaders/Request`, `emitContext` | Hook dispatch (incl. permission gate) |
| `src/core/extensions/loader.ts` | `loadExtensionsCached`, `createExtensionRuntime` | Extension loading |

## AI / provider layer (ai)

| File | Key symbols | Role |
|------|-------------|------|
| `src/compat.ts` | `streamSimple` (dispatch), `completeSimple`, `registerApiProvider` | Compat entrypoint (`@earendil-works/pi-ai/compat`) |
| `src/models.ts` | `createModels`, `createProvider`, `clampThinkingLevel`, `calculateCost` | Provider/model plumbing |
| `src/api/*.ts` (e.g. `anthropic-messages.ts`) | `stream`, `streamSimple` | Per-provider request build + SSE/WS parse |
| `src/api/lazy.ts` | `lazyApi`, `lazyStream` | Lazy provider import |
| `src/utils/event-stream.ts` | `EventStream`, `AssistantMessageEventStream` | Push/end/result stream |
| `src/utils/validation.ts` | `validateToolArguments`, `validateToolCall` | Tool-arg schema validation |
| `src/utils/overflow.ts` | `isContextOverflow` | Overflow detection |
| `src/utils/retry.ts` | `isRetryableAssistantError` | Retry classification |
| `src/types.ts` | `Context`, `Message`, `AssistantMessage`, `ToolResultMessage`, `Model`, `AssistantMessageEvent`, `SimpleStreamOptions`, `Transport`, `ThinkingBudgets` | Provider-facing types |

## Runtime dependency direction

Observed runtime direction for the pi packages: **coding-agent → agent → ai**
(coding-agent depends on agent-core and ai; agent-core depends on ai via
`@earendil-works/pi-ai/compat`; ai depends on neither). **[verified for pi packages]**

The repo-wide `AGENTS.md` convention (Schema → Core & Protocol → Server; Client
depends on Schema & Protocol but never Core or Server; `sdk-next` composes Client,
Core, Server) applies to the broader monorepo, not specifically these pi
packages. **[unverified for pi]**
