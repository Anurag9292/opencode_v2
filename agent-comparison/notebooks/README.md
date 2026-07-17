# Notebooks

Runnable companions to the markdown report in the parent folder. One per agent, plus a
comparative overview.

| Notebook | Contents |
|---|---|
| `00_overview.ipynb` | The core thesis; verifies all three condensed harnesses import; headline comparison table |
| `01_opencode.ipynb` | OpenCode architecture; **live-verifies** the real core (`while(true)` loop, permission `evaluate`, snapshot/task tools); runs the `mini-agent` distillation offline |
| `02_openhands.ipynb` | OpenHands control-plane/external split; **live-verifies** dispatch + webhook + sandbox-callback code; runs the `agent_harness` distillation offline |
| `03_pi.ipynb` | PI minimal loop; **live-verifies** `prepareToolCall` + "no MCP in source"; runs the `pi/agent_harness` distillation offline |

## How they work

Each notebook:
1. Auto-detects the repo root (`find_repo_root()` — looks for `mini-agent`/`pi`/`openhands_all`).
2. Prints slices of the **real shipping source** so every architectural claim is checkable
   against the implementation (`show(relpath, needle)`).
3. Runs the project's **condensed harness** with a scripted/echo model — **offline, no API key,
   stdlib only** — so you can watch a full turn (tool call → result → final) and its event trace.

## Run

```bash
# With Jupyter:
cd agent-comparison/notebooks
jupyter lab            # or: jupyter notebook

# Without Jupyter (execute cells headless to verify they still work):
python - <<'PY'
import json, io, contextlib
for f in ["00_overview","01_opencode","02_openhands","03_pi"]:
    nb = json.load(open(f+".ipynb")); ns={}
    for c in nb["cells"]:
        if c["cell_type"]=="code":
            exec("".join(c["source"]), ns)
    print("ran", f)
PY
```

They are dependency-free (no `nbconvert`/`ipykernel` needed to *read*; a kernel is only needed
to run them interactively). All four were executed end-to-end during authoring.
