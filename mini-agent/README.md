# miniagent

A minimal educational coding-agent harness in pure Python (zero dependencies,
stdlib only). Ten small interfaces, one legible turn loop, real tools with a
permission gate, and a JSONL trace of everything.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the component diagram, event flow,
and the development sequence from echo loop to production harness.

## Run it

```bash
# interactive agent in the current directory (requires ANTHROPIC_API_KEY)
cd mini-agent
ANTHROPIC_API_KEY=sk-... python3 -m miniagent /path/to/workspace
```

## Test it (no network needed)

```bash
cd mini-agent
python3 -m unittest discover tests -v
```

The tests fake only the network boundary (a `ScriptedProvider` that plays
back model turns); the store, loop, tools, permissions, bus, and trace are
all real.

## Use it as a library

```python
import asyncio
from miniagent import LocalSession, AnthropicProvider, Rule

session = LocalSession(
    provider=AnthropicProvider(),
    workdir="/path/to/workspace",
    rules=[Rule(action="write", pattern="src/*", decision="allow"),
           Rule(action="bash", pattern="rm *", decision="deny")],
)
final = asyncio.run(session.prompt("add a hello() function to src/app.py"))
print(final.text())
```

## Where to start reading

1. `miniagent/impl/loop.py` — the turn loop; the whole idea lives here
2. `miniagent/types.py` — the message/part data model
3. `miniagent/interfaces/` — the ten seams, one Protocol per file
4. `miniagent/impl/session.py` — how it all wires together
