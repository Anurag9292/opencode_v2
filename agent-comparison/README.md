# Architectural Comparison: OpenCode vs OpenHands vs PI

An implementation-driven reverse-engineering and comparison of three AI coding agents.
This is written for engineers who want to understand *how these systems actually work*
and *why* each made the design choices it did — not a feature checklist.

## What's in here

| File | Contents |
|---|---|
| [`01-overview-and-thesis.md`](01-overview-and-thesis.md) | The one core difference, methodology, per-agent high-level architecture + major components |
| [`02-agent-loop-and-state.md`](02-agent-loop-and-state.md) | Execution loop, planning vs acting, where reasoning happens, where state lives |
| [`03-tools-and-execution.md`](03-tools-and-execution.md) | Tool discovery/execution, parallel vs sequential, errors/retries, execution env / sandboxing / security |
| [`04-context-filesystem-prompts.md`](04-context-filesystem-prompts.md) | Context/memory/compaction, filesystem/patch/git, prompt architecture, streaming/UI |
| [`05-orchestration-and-extensibility.md`](05-orchestration-and-extensibility.md) | Single vs multi-agent, delegation, extensibility (tools/plugins/MCP/config) |
| [`06-code-walkthrough-and-callgraphs.md`](06-code-walkthrough-and-callgraphs.md) | Most important files per project + user-request→response call graphs |
| [`07-comparison-tables.md`](07-comparison-tables.md) | All required comparison tables in one place |
| [`08-unique-ideas-and-design-lessons.md`](08-unique-ideas-and-design-lessons.md) | Innovations unique to each + what to borrow for a next-gen agent |
| [`09-discrepancies-and-caveats.md`](09-discrepancies-and-caveats.md) | Doc-vs-implementation discrepancies and verification caveats |
| [`10-request-lifecycle-and-memory.md`](10-request-lifecycle-and-memory.md) | **Cognition deep-dive:** trace "build me a todo app" — memory storage, purge/keep policy, sub-agent memory, relevance mechanisms |
| [`notebooks/`](notebooks/) | Runnable Jupyter notebooks — one per agent + a comparative overview |

## Sources analyzed (paths relative to repo root `/repo`, the prompt's `home/`)

| Project | Core implementation | Condensed harness | Docs |
|---|---|---|---|
| **OpenCode** | `packages/opencode/src` (+ `packages/core`, `packages/llm`) — TypeScript, Effect runtime | `mini-agent/miniagent` (Python) | `mini-agent/ARCHITECTURE.md`, `README.md` |
| **OpenHands** | `openhands_all/app_server` (Python, control plane) + **external** `openhands.sdk`/`openhands.agent_server` (not vendored) | `openhands_all/agent_harness/harness` (Python) | `openhands_all/docs/*` |
| **PI** | `pi/packages/{agent,coding-agent,ai,tui}` — TypeScript, plain async | `pi/agent_harness/agent_harness` (Python) | `pi/docs/*` |

## Methodology (as required)

1. **Documentation first.** We read every project's docs to build a mental model.
2. **Verified against implementation.** Every architectural claim was checked against the
   actual source; claims carry `file:symbol` citations.
3. **Implementation-driven.** Where docs and code disagree, the code wins and the
   discrepancy is called out (see `09-discrepancies-and-caveats.md`).
4. **External boundaries are marked.** OpenHands runs its real agent loop in an external,
   non-vendored `openhands-agent-server`; anything inside it is tagged `[EXTERNAL]` /
   `(unverified)` because it is not on disk in this repo.

## The 30-second thesis

- **OpenCode** — a **local, richly-featured, Effect-structured single-process engine**. It
  owns the entire loop, executes tools in-process behind a permission gate, and treats the
  transcript (SQLite) + per-turn git snapshots as the source of truth. Optimizes for a
  *powerful local coding agent with safety rails and deep IDE/tooling integration*.
- **OpenHands** — a **distributed, event-sourced control plane**. `app_server` never runs the
  loop; it provisions a **sandbox**, assembles an `Agent` request, POSTs it to an external
  agent-server, and receives events back via **webhook**. Optimizes for *multi-tenant, secure,
  horizontally-scalable cloud execution*.
- **PI** — a **minimal, extensible local harness**. A tiny model-agnostic loop with **no
  built-in permissions, no MCP, no sub-agents, no plan mode** — everything non-essential is
  pushed into a first-class **extension API**. Optimizes for *a small legible core you bend to
  your workflow*.

Read `01-overview-and-thesis.md` next.
