# miniagent — Architecture

A minimal educational coding-agent harness, distilled from studying OpenCode's
architecture (turn loop, message parts, tool registry, permission gate, event
bus) without reproducing its implementation. Everything is plain Python with
zero dependencies.

The core idea worth teaching: **a coding agent is a while-loop over a durable
transcript.** Each iteration makes exactly one model call, persists what
streamed, executes whatever tools the model requested, and loops until the
model stops asking for tools. Every other component exists to keep that loop
small.

## 1. Component diagram

```
                                  ┌────────────────────┐
                    prompt(text)  │      Session       │  composition root:
   user/CLI ────────────────────► │   (impl/session)   │  owns id + wiring,
                                  └─────────┬──────────┘  no behavior
                                            │ run(session_id, text)
                                            ▼
        ┌────────────────────────────────────────────────────────────┐
        │                        AgentLoop                           │
        │                      (impl/loop.py)                        │
        │                                                            │
        │   while not finished:                                      │
        │     history = store.history()          ──► MessageStore    │
        │     ctx     = context.build(history)   ──► ContextBuilder  │
        │     events  = provider.stream(ctx)     ──► ModelProvider   │
        │     persist parts as they arrive       ──► MessageStore    │
        │     for call in tool_calls:                                │
        │       registry.get(call.tool)          ──► ToolRegistry    │
        │         tool.execute(args, ctx) ─┬───► Tool                │
        │                                  └ ctx.ask() ─► Permission │
        │                                                 Policy     │
        │     publish(everything)                ──► EventBus        │
        └────────────────────────────────────────────────────────────┘
                                            │ publish
                                            ▼
                                  ┌────────────────────┐
                                  │      EventBus      │
                                  └───┬────────────┬───┘
                          subscribe   │            │   subscribe("*")
                                      ▼            ▼
                              ┌───────────┐  ┌───────────────┐
                              │  CLI /UI  │  │ TraceRecorder │
                              │ (render)  │  │   (JSONL)     │
                              └───────────┘  └───────────────┘
```

Dependency rules (the arrows only point one way):

- The **AgentLoop** depends on every interface but on no implementation.
- **Tools** know nothing about the loop; they receive a `ToolContext` and call
  `ctx.ask()` for permissions.
- The **EventBus** is publish-only from the loop's perspective; the CLI and the
  TraceRecorder are just subscribers. Deleting them changes nothing.
- The **MessageStore** is the single source of truth for history. The loop
  re-reads it every turn instead of holding messages in local variables — this
  discipline is what later enables resume, multi-observer UIs, and sub-agents.

## 2. Event flow (one prompt with one tool call)

```
 user            AgentLoop        ModelProvider     Tool        PermissionPolicy   EventBus
  │ prompt(text)     │                  │             │                │              │
  ├────────────────► │ save(user msg)   │             │                │              │
  │                  ├──────────────────┼─────────────┼────────────────┼──message.created
  │            turn 1│ build context    │             │                │              │
  │                  ├─ stream(ctx) ──► │             │                │              │
  │                  │ ◄─ TextDelta ────┤             │                │              │
  │                  ├──────────────────┼─────────────┼────────────────┼──message.part.delta
  │                  │ ◄─ ToolCallReq ──┤             │                │              │
  │                  │ ◄─ Finish(tool_calls)          │                │              │
  │                  ├──────────────────┼─────────────┼────────────────┼──message.updated
  │                  ├──────────────────┼─────────────┼────────────────┼──tool.started
  │                  ├─ execute(args) ──┼───────────► │                │              │
  │                  │                  │             ├── ctx.ask() ─► │              │
  │                  │                  │             │      allow/ask/deny           │
  │                  │                  │             │                ├─permission.asked
  │                  │                  │             │ ◄── ok/raise ──┤              │
  │                  │ ◄─ ToolResult ───┼─────────────┤                │              │
  │                  │ save(part: completed + output) │                │              │
  │                  ├──────────────────┼─────────────┼────────────────┼──tool.finished
  │            turn 2│ re-read history (tool output now in it)         │              │
  │                  ├─ stream(ctx) ──► │             │                │              │
  │                  │ ◄─ TextDelta / Finish(stop)    │                │              │
  │                  ├──────────────────┼─────────────┼────────────────┼──session.idle
  │ ◄── final msg ───┤                  │             │                │              │
```

Key properties:

- **Tool results re-enter the conversation through the store**, not through
  local variables: they're written onto the `ToolCallPart` of the assistant
  message, and the provider adapter encodes completed parts as tool-result
  blocks on the next call.
- **Failures are data.** Unknown tool, permission denial, or a tool exception
  all become `status: error` + a model-readable message on the part. The model
  sees the error next turn and adapts; the loop never crashes on a tool.
- **Persist after every stream event.** A crash mid-turn loses nothing that
  already streamed, and any observer sees live state.

## 3. Interface skeletons

The ten seams live one-per-file in `miniagent/interfaces/`, as
`typing.Protocol`s (structural — no inheritance needed). Condensed:

```python
class ModelProvider(Protocol):        # interfaces/model.py
    def stream(self, context: ModelContext,
               tools: list[ToolSpec]) -> AsyncIterator[ModelEvent]: ...
    # ModelEvent = TextDelta | ToolCallRequest | Finish  (normalized stream)

class MessageStore(Protocol):         # interfaces/store.py
    def save(self, message: Message) -> None: ...          # upsert by id
    def history(self, session_id: str) -> list[Message]: ...

class ContextBuilder(Protocol):       # interfaces/context.py
    def build(self, session_id: str,
              history: list[Message]) -> ModelContext: ...

class Tool(Protocol):                 # interfaces/tool.py
    def spec(self) -> ToolSpec: ...   # name, description, JSON-schema params
    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult: ...

class ToolRegistry(Protocol):         # interfaces/tool.py
    def specs(self) -> list[ToolSpec]: ...
    def get(self, name: str) -> Tool | None: ...

class PermissionPolicy(Protocol):     # interfaces/permission.py
    def check(self, request: PermissionRequest) -> None: ...  # allow/ask/deny
    def reply(self, request: PermissionRequest, reply: Reply) -> None: ...

class EventBus(Protocol):             # interfaces/events.py
    def publish(self, event: Event) -> None: ...
    def subscribe(self, type: str,
                  handler: Callable[[Event], None]) -> Callable[[], None]: ...

class TraceRecorder(Protocol):        # interfaces/trace.py
    def record(self, event: Event) -> None: ...
    def read(self, session_id: str) -> list[Event]: ...

class AgentLoop(Protocol):            # interfaces/loop.py
    async def run(self, session_id: str, user_text: str) -> Message: ...

class Session(Protocol):              # interfaces/session.py
    @property
    def id(self) -> str: ...
    async def prompt(self, text: str) -> Message: ...
```

Shared data types (`miniagent/types.py`): `Message` is a role-tagged record
holding an ordered list of typed **parts** (`TextPart`, `ToolCallPart`); a
`ToolCallPart` is a small state machine (`pending → running →
completed|error`) that carries its own output. This "message of parts" model
is the single most load-bearing design decision borrowed from production
harnesses: the full story of a turn lives inside the message that caused it.

## 4. Directory structure

```
mini-agent/
├── ARCHITECTURE.md              this document
├── README.md                    quick start
├── miniagent/
│   ├── __init__.py              public exports
│   ├── __main__.py              interactive CLI (python -m miniagent)
│   ├── types.py                 Message, Part, ModelEvent, ToolSpec, Event, ...
│   ├── interfaces/              the 10 seams, one Protocol per file
│   │   ├── model.py  store.py  context.py  tool.py  permission.py
│   │   ├── events.py  trace.py  loop.py  session.py
│   │   └── __init__.py
│   ├── impl/                    reference implementations
│   │   ├── loop.py              ★ the turn loop — read this first
│   │   ├── session.py           composition root
│   │   ├── anthropic.py         real provider (stdlib HTTP, no SDK)
│   │   ├── scripted.py          deterministic fake provider for tests
│   │   ├── store.py             JSON-file MessageStore
│   │   ├── context.py           system prompt + env + AGENTS.md
│   │   ├── registry.py          dict-backed ToolRegistry
│   │   ├── permission.py        wildcard rules, last-match-wins, default ask
│   │   ├── events.py            in-memory EventBus
│   │   └── trace.py             JSONL TraceRecorder (bus subscriber)
│   └── tools/
│       └── builtin.py           read, write, list, bash (+ path sandboxing)
└── tests/
    └── test_harness.py          end-to-end: scripted provider, real everything else
```

Runtime data lands in `<workdir>/.miniagent/{sessions,trace}/` — open the
JSON/JSONL files to inspect exactly what the agent saw and did.

## 5. Development sequence: simplest loop → production harness

Each stage is shippable and testable before the next.

1. **Echo loop.** `Message`/`Part` types, `ModelProvider` with one
   non-streaming call, no tools. Prompt in, text out. Proves the provider
   adapter and message model.
2. **Tool calls, hardcoded toolset.** Add `ToolCallPart`, the
   `Finish(tool_calls)` branch, and a `read` tool wired directly into the
   loop. The while-loop is now real: model → tool → model.
3. **Durable transcript.** Introduce `MessageStore`; make the loop re-read
   history each turn and persist after every stream event. Now a session can
   be resumed and inspected on disk.
4. **Registry + write tools + permissions.** `ToolRegistry`, `write`/`bash`,
   `PermissionPolicy` with allow/ask/deny wildcard rules and a human asker.
   Errors and denials become tool output, never crashes.  ← *v1 ships here
   (this repo).*
5. **Events + trace + UI.** `EventBus`, `TraceRecorder` as a wildcard
   subscriber, CLI rendering driven purely by events. Also part of this repo —
   it proves that observability is additive.
6. **True streaming + robustness.** SSE streaming in the provider (only
   `impl/anthropic.py` changes), abort/cancel via signal in `ToolContext`,
   retries with backoff, output-truncation-to-file, token/cost accounting.
7. **Context management.** Token counting, tool-output truncation policy,
   then compaction: summarize-and-cut when the window overflows (a summary
   message that `history()` filters behind).
8. **Sub-agents.** A `task` tool that creates a child session with a derived
   (narrower) permission ruleset and returns its final text as tool output.
   Requires nothing new — it is the same loop recursively, which is the punchline.
9. **Production hardening.** SQLite store, concurrent-prompt policy (queue or
   join), server + SSE for remote clients, provider catalog/auth, sandboxed
   bash, evals built on the trace files.

## 6. OpenCode complexities deliberately excluded from v1

| Excluded | Why it's safe to skip at first |
|---|---|
| Compaction / summarization / overflow detection | Needs token accounting and prompt tuning; short sessions fit in-window. Stage 7. |
| Snapshots & revert (git-based file state per turn) | Orthogonal safety feature; the permission gate covers the teaching goal. |
| Effect-style service/layer runtime | Plain async/await keeps the loop legible — the point of the exercise. |
| Durable execution (input admission, run coordinator, crash-resume, clustering) | Deep distributed-systems territory; v1's "store is truth" discipline leaves the door open. |
| MCP servers, plugin hooks, skills, LSP integration | Toolset extensibility beyond a dict registry; the `ToolRegistry` seam is where they'd land. |
| Provider catalog, auth flows, model failover, request transforms | One hardcoded provider demonstrates the seam; the rest is inventory management. |
| Multi-client sync, share/server SSE, TUI/desktop apps | The EventBus already proves the decoupling; transports are plumbing. |
| Streaming tool-input deltas, reasoning parts, file/patch parts | More part types on an established pattern; no new concepts. |
| Sub-agents / task tool | Excluded from v1 only for size — stage 8 shows it's the same loop recursively. |
| Output truncation-to-file, shell session reuse, background tasks | Ergonomics, not architecture. |

The inclusion test used throughout: **does it teach the loop, or does it
scale the loop?** v1 keeps everything in the first category.
