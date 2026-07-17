# 5. Task Orchestration & Extensibility

## 5.1 Single-agent vs multi-agent, subtasks, delegation

| | Multi-agent | Subtask decomposition | Delegation mechanism |
|---|---|---|---|
| **OpenCode** | **Yes, built-in.** `tool/task.ts` (`TaskTool`) spawns a **child session running the same loop recursively** via `SessionPrompt.prompt`; agents defined in `agent/agent.ts` (`mode: primary|subagent`, per-agent permission/model/steps) | The `task` tool + `SubtaskPart` (handled by `handleSubtask`, `prompt.ts:255`); supports **background** execution (`BackgroundJob.Service`) | Child session gets a **derived, narrowed permission ruleset** (`agent/subagent-permissions.ts:deriveSubagentSessionPermission`); returns final text as the tool result |
| **OpenHands** | **Yes**, via a separate **planning agent** (`AgentType.PLAN`) + registered sub-agents (`get_registered_agent_definitions()`, attached only when `enable_sub_agents`) + **ACP agents** (Claude Code/Codex CLIs) as an entirely separate request builder (`_build_acp_start_conversation_request`, `:2001`) | Planning agent produces `PLAN.md`, hands off to the code agent (execution boundary enforced by `PLANNING_AGENT_INSTRUCTION`) | Sub-conversations **inherit** sandbox/git/model from parent (`_inherit_configuration_from_parent`, `:1047`); delegation execution is `[EXTERNAL]` |
| **PI** | **No, by design.** No built-in sub-agents, task tool, or plan mode (`docs/usage.md:307`) | Composed via extensions (`examples/extensions/subagent`) | An extension spawns/coordinates its own sub-sessions using the SDK; nothing in core |

**Comparison:** three different answers to "how do you decompose work":
- **OpenCode** — *recursion*: a subtask is just the same loop in a child session with narrower
  permissions. Elegant and uniform.
- **OpenHands** — *typed agents*: a dedicated planning agent + pluggable sub-agent definitions +
  external CLI agents, coordinated by the control plane with inherited sandbox/config.
- **PI** — *nothing*: decomposition is an extension you write; the core stays a single loop.

## 5.2 Extensibility: new tools, plugins, MCP, config

### OpenCode — plugin system + MCP + skills + config, all first-class
- **Plugins** (`plugin/`, `Plugin.Service`): `trigger(name, input, output)` invokes hooks that
  mutate output in place. Hooks seen: `tool.execute.before/after`, `tool.definition`,
  `chat.message`, `command.execute.before`, `shell.env`,
  `experimental.chat.messages.transform`, `experimental.text.complete`. Plugins can add tools
  (`p.tool`) and providers.
- **MCP** (`mcp/index.ts`, `MCP.Service`): full client — `clients/tools/instructions/resources/
  readResource/resourceTemplates`; MCP tools merged into the toolset (`SessionTools.resolve`)
  each gated by `ctx.ask`; OAuth support (`mcp/oauth-provider.ts`).
- **Skills** (`skill/index.ts`): discovers `**/SKILL.md` under `.opencode`, `.claude/skills`,
  `.agents/skills`; exposed in the system prompt; loaded on demand by `SkillTool`.
- **LSP** (`lsp/`): diagnostics/formatting integrated into edits.
- **Config** (`config/config.ts`): JSON/JSONC + markdown-frontmatter agents/commands.
- **Adding a tool:** `Tool.define(id, ...)`, import in `tool/registry.ts`, add to arrays; or
  drop a file in `tool/`, or ship it from a plugin.

### OpenHands — marketplace skills, hooks, MCP proxy, event callbacks, DI
- **Skills/microagents:** proxied to the agent-server (`skill_loader.load_skills_from_agent_server`,
  `:505`), composed across **instance/org/user marketplaces** (`marketplace_composition.py`),
  merged/deduped, deny-list honored.
- **Hooks:** `hook_loader.load_hooks_from_agent_server` (agent-server `/api/hooks`).
- **MCP:** app_server both **consumes** MCP (custom servers from user settings via
  `_merge_custom_mcp_config`) and **hosts** an MCP server at `/mcp` — specifically a **Tavily
  search proxy** (`mcp/mcp_router.py:init_tavily_proxy`) so the sandbox never sees the Tavily key.
- **Event callbacks/processors:** pluggable `EventCallbackProcessor` (e.g.
  `SetTitleCallbackProcessor`) run off the hot path — this is a server-side extension point.
- **Config:** dependency-injection **injectors** (`config.py`) choose concrete services
  (event backend, sandbox impl, service bindings), overridable via env / `get_impl`.

### PI — one extension API is *the* extensibility story (and it's large)
`coding-agent/src/core/extensions/{types,runner,loader}.ts`. A single `ExtensionAPI` object
passed to `(pi) => {...}` factories. It exposes:
- **Registration:** `registerTool`, `registerCommand` (slash commands), `registerShortcut`,
  `registerFlag`/`getFlag`, `registerMessageRenderer`/`registerEntryRenderer`,
  `registerProvider`/`unregisterProvider` (custom LLM providers incl. custom `streamSimple`),
  plus actions `sendMessage`/`sendUserMessage`/`appendEntry`/`setModel`/`setThinkingLevel`/`setActiveTools`.
- **Event hooks (the loop's seams):** `before_agent_start` (append messages / override system
  prompt), `tool_call` (**the permission gate**), `tool_result`, `context` (rewrite messages
  before the LLM), `before_provider_request`, `before_provider_headers`, `after_provider_response`,
  `input`, `user_bash`, session lifecycle (`session_before_switch/fork/compact/tree`,
  `session_shutdown`, `project_trust`), `model_select`, `thinking_level_select`, and all the
  `message_*`/`tool_execution_*`/`turn_*`/`agent_*` events.
- **Loader:** discovers `.pi/extensions/`, `agentDir/extensions/`, and configured paths; loads
  via **jiti** with bundled virtual modules; supports pi packages via npm/git.
- **MCP:** **none in core** — "No MCP by design; build an extension that adds it"
  (`README.md:493`, verified no MCP source).

### Extensibility comparison

| Axis | OpenCode | OpenHands | PI |
|---|---|---|---|
| New tool | registry entry / `tool/*.ts` file / plugin | `openhands.tools` `[EXTERNAL]` + marketplace | `pi.registerTool` (extension) |
| Plugin/hook model | plugin hooks mutate in/out | server-side event-callback processors + hooks proxied to agent-server | one `ExtensionAPI` with ~30 event hooks + registration methods |
| MCP | **full client + OAuth** | **consumes** custom + **hosts** a Tavily proxy | **none** (deliberate; do it in an extension) |
| Providers | provider catalog + plugins (`plugin/openai`, `github-copilot`, `azure`, `xai`) | LLM profiles + `resolve_provider_llm_base_url` | 35 built-in catalogs + `registerProvider` extension |
| Config | JSON/JSONC + markdown frontmatter | DI injectors + settings store + marketplaces | `settings.json` (global/project) + extension flags |

**Comparison:** OpenCode and PI put extensibility **in the loop's process** (plugins/extensions
run alongside the agent). OpenHands puts extensibility at **platform seams** (marketplace skills,
server callbacks, an MCP proxy) because the agent itself is a sandboxed black box. PI is
notable for making the **extension API the product**: the core is small precisely so that MCP,
sub-agents, plan mode, and permissions are *your* extensions — the opposite of OpenCode's
"batteries included" and OpenHands' "platform provides it."
