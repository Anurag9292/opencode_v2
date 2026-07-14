# Agent Turn Sequence — `openhands_all` (`app_server`)

This document traces **one complete agent turn** as it flows through the code in
`openhands_all/app_server`. It cites the exact file, exported symbol, and the
important function calls at each step.

> **Critical architectural fact (VERIFIED).**
> `openhands_all/app_server` is an **orchestrator / control plane**. It does **not**
> run the agent loop itself. The real agent turn — system-prompt string rendering,
> the LLM/model request, streamed response parsing, tool-call detection, permission /
> confirmation enforcement, and tool execution — all happen inside the **external
> `openhands-agent-server`** process (which itself uses `openhands-sdk` /
> `openhands-tools`). Those packages are **not vendored in this repo** (confirmed:
> no `openhands.sdk` / `openhands.agent_server` source on disk; the only local
> `openhands.*` package is `openhands.app_server`).
>
> `app_server` therefore:
> 1. Provisions a sandbox running the agent-server.
> 2. **Assembles** the `Agent` + `StartConversationRequest` (LLM, tools, skills,
>    hooks, secrets, system-message suffix, confirmation policy).
> 3. **POSTs** that request to the agent-server to start the turn.
> 4. Receives events back via an **inbound webhook** (the agent-server calls
>    `app_server`, not the other way around — no polling).
> 5. **Persists** those events and runs registered callbacks.
>
> Steps that occur inside the external agent-server are marked **[EXTERNAL]** and,
> where their internal mechanics cannot be confirmed from this repo, **(unverified)**.

Unless noted, all paths are relative to `openhands_all/`.

---

## Layer overview

```
Client ──HTTP──> app_server (FastAPI, this repo)
                   │  assembles Agent + StartConversationRequest
                   │  POST {agent_server_url}/api/conversations           (start turn)
                   │  POST {agent_server_url}/api/conversations/{id}/events (user input)
                   ▼
             agent-server  [EXTERNAL, in sandbox]
                   │  runs the agent loop:
                   │   system prompt → model stream → tool-call detection
                   │   → permission/confirmation → tool execution → next iteration
                   │
                   └──HTTP POST /api/v1/webhooks/events/{id}──> app_server
                                                                 persists + callbacks
```

---

## Step 1 — User input / request entry

**File:** `app_server/app.py`
**Symbol:** module-level `app` (`FastAPI`)
- Mounts the API router: `app.include_router(v1_router.router)` (`app.py:71`) and
  the health router `app.include_router(health_router)` (`app.py:72`).
- Mounts the MCP sub-app at `/mcp` (`app.py:59`).

**File:** `app_server/v1_router.py`
**Symbol:** `router` = `APIRouter(prefix='/api/v1')` (`v1_router.py:24`)
- `include_router(app_conversation_router)` → `/api/v1/app-conversations` (`v1_router.py:26`)
- `include_router(pending_message_router)` → `/api/v1/conversations/{id}/pending-messages` (`v1_router.py:27`)
- `include_router(event_router)` (`v1_router.py:25`) and `include_router(webhook_router)` (`v1_router.py:34`)

Two ways user input enters a turn:

1. **Start a new conversation with an initial message** —
   `POST /api/v1/app-conversations`
   → `AppConversationStartRequest.initial_message`
   (`app_server/app_conversation/app_conversation_models.py:231`).
2. **Send input to a running conversation** —
   `POST /api/v1/app-conversations/{id}/send-message`
   → `AppSendMessageRequest` (`app_conversation_models.py:376`).
   Or queue it before READY via
   `POST /api/v1/conversations/{id}/pending-messages`.

---

## Step 2 — Session / conversation creation

**File:** `app_server/app_conversation/app_conversation_router.py`
**Symbol / handler:** `start_app_conversation` (`app_conversation_router.py:365`)
- Keeps DB + HTTP connections open past the response:
  `set_db_session_keep_open(request.state, True)` (`:376`),
  `set_httpx_client_keep_open(request.state, True)` (`:377`).
- Kicks off the start generator:
  `async_iter = app_conversation_service.start_app_conversation(start_request)` (`:381`).
- Returns the **first** yielded task (status `WORKING`) immediately:
  `result = await anext(async_iter)` (`:382`).
- Drives the rest in the background:
  `asyncio.create_task(_consume_remaining(async_iter, db_session, httpx_client))` (`:406`).
- Background driver `_consume_remaining` loops `await anext(async_iter)` until
  `StopAsyncIteration` (`app_conversation_router.py:1659`).

**File:** `app_server/app_conversation/live_status_app_conversation_service.py`
**Symbol:** `LiveStatusAppConversationService` (`:240`),
subclass of `AppConversationServiceBase`.
- Public wrapper `start_app_conversation` (`:352`) persists **every** yielded task,
  then re-yields it:
  ```
  async for task in self._start_app_conversation(request):
      await self.app_conversation_start_task_service.save_app_conversation_start_task(task)  # :356
      yield task
  ```
- The status machine lives in `_start_app_conversation` (`:361`) and progresses:
  `WORKING → WAITING_FOR_SANDBOX → PREPARING_REPOSITORY → RUNNING_SETUP_SCRIPT →
   SETTING_UP_GIT_HOOKS → SETTING_UP_SKILLS → STARTING_CONVERSATION → READY`
  (enum `AppConversationStartTaskStatus`,
  `app_conversation_models.py:288`).

**Sandbox acquisition** (`WAITING_FOR_SANDBOX`):
- `_wait_for_sandbox_start(task)` (`:394`, defined `:888`):
  `sandbox_service.start_sandbox(...)` (`:906`),
  `sandbox_service.wait_for_sandbox_running(...)` (`:951`).
- Agent-server URL resolved from the sandbox's exposed URLs:
  `_get_agent_server_url(sandbox)` (`:402`, defined `:1035`).

**Task persistence backend:**
**File:** `app_server/app_conversation/sql_app_conversation_start_task_service.py`
**Symbol:** `SQLAppConversationStartTaskService.save_app_conversation_start_task` (`:235`)
- `session.merge(StoredAppConversationStartTask(**task.model_dump()))` (`:246`) +
  `session.commit()` (`:247`). Table `app_conversation_start_task`
  (`StoredAppConversationStartTask`, `:54`).

---

## Step 3 — Instruction / skill / hook / secret loading

All of these are **gathered here** and attached to the request; the directories
`.openhands/skills`, `.openhands/microagents`, `.openhands/hooks.json` are actually
**read inside the agent-server** (via the HTTP endpoints below), not in this repo.

**Repository preparation** (`PREPARING_REPOSITORY` → `RUNNING_SETUP_SCRIPT`):
**File:** `app_server/app_conversation/app_conversation_service_base.py`
- `run_setup_scripts` (`:269`) drives the middle statuses.
- `clone_or_init_git_repo` (`:342`) → `workspace.execute_command('... git clone ...')`
  (`:414`) via `AsyncRemoteWorkspace` **[EXTERNAL SDK]**;
  auth URL from `user_context.get_authenticated_git_url(...)` (`:376`).
- `maybe_run_setup_script` (`:538`) → `source .openhands/setup.sh` (`:551`).
- `get_project_dir(working_dir, selected_repository)` (`:56`) — resolves the repo root.

**Git hooks** (`SETTING_UP_GIT_HOOKS`):
**File:** `app_server/app_conversation/app_conversation_service_base.py`
- `maybe_setup_git_hooks` (`:557`) uploads the shim
  `app_server/app_conversation/git/pre-commit.sh` to `.git/hooks/pre-commit`
  via `workspace.file_upload(...)` (`:599`); preserves any prior hook as
  `pre-commit.local` (`:585`).

**File:** `app_server/app_conversation/hook_loader.py`
- `load_hooks_from_agent_server(...)` (`:103`) / `fetch_hooks_from_agent_server` (`:43`)
  → `POST {agent_server_url}/api/hooks` (`:78`); parses `HookConfig.from_dict`
  (`:93`, `HookConfig` from `openhands.sdk.hooks` **[EXTERNAL]**).

**Skills / microagents** (`SETTING_UP_SKILLS`):
**File:** `app_server/app_conversation/app_conversation_service_base.py`
- `load_and_merge_all_skills(...)` (`:100`) → `build_org_configs` (`:139`),
  `build_sandbox_config` (`:144`), `authenticate_marketplace_sources` (`:149`),
  `load_skills_from_agent_server` (`:154`).
- `_create_agent_with_skills(agent, skills)` (`:179`) merges skills into
  `agent.agent_context.skills` via `agent.model_copy(...)` (`:193`).

**File:** `app_server/app_conversation/skill_loader.py`
- `load_skills_from_agent_server(...)` (`:505`) → `POST {agent_server_url}/api/skills`
  (`:573`); converts responses to `openhands.sdk.skills.Skill` via
  `_convert_skill_info_to_skill` (`:620`) attaching `KeywordTrigger` / `TaskTrigger`
  **[EXTERNAL SDK types]**.

**Secrets:**
**File:** `app_server/app_conversation/conversation_secret_enricher.py`
- `ConversationSecretEnricher.enrich(...)` (`:29`) — extension point; **no-op in
  this repo** (returns only the `system_message_suffix`, `:40`).

**File:** `app_server/app_conversation/live_status_app_conversation_service.py`
- `_setup_conversation_secrets(...)` (`:1179`) → `_setup_secrets_for_git_providers`
  (`:1195`) builds `LookupSecret(url=web_url + '/api/v1/webhooks/secrets', ...)`
  (`:1162`) or `StaticSecret(...)` (`:1173`) **[EXTERNAL SDK secret types]**.

**Settings feed (LLM / model / api-key):**
**File:** `app_server/settings/settings_store.py` — `SettingsStore.load(resolve_agent_profile=True)` (`:22`).
**File:** `app_server/settings/settings_models.py` — `Settings.agent_settings` (`:376`),
`conversation_settings` (`:377`, holds `confirmation_mode`, `security_analyzer`).
**File:** `app_server/settings/llm_profiles.py` — `resolve_profile_llm(...)` (`:37`, forces `stream=True`).

---

## Step 4 — System-prompt construction & model-request assembly

The **string** of the system prompt is rendered **[EXTERNAL]** inside the SDK from a
Jinja template (the only local trace is the filename literal
`'system_prompt_planning.j2'`, `live_status_app_conversation_service.py:1419`).
This repo assembles the **inputs** to it.

**File:** `app_server/app_conversation/live_status_app_conversation_service.py`
**Symbol:** `_build_start_conversation_request_for_user` (`:1630`)
- Load effective user/settings:
  `user_context.get_user_info(resolve_agent_profile=True, ...)` (`:1683`).
- **LLM config:** `_configure_llm_and_mcp(...)` (`:1757`) → `_configure_llm` (`:1215`);
  forces `stream=True`, `usage_id='agent'` (`:1252`) on the SDK `LLM`.
- **MCP:** `_add_system_mcp_servers` (`:1254`) adds an `MCPServer` at `{web_url}/mcp/mcp`.
- **Tools [EXTERNAL `openhands.tools`]:**
  PLAN → `get_planning_tools(...)` (`:1786`);
  DEFAULT → `register_builtins_agents(enable_browser=True)` (`:1788`) +
  `get_default_tools(...)` (`:1789`); sub-agents via
  `get_registered_agent_definitions()` (`:1794`).
- **System-message suffix** assembled from:
  `request.system_message_suffix`,
  `PLANNING_AGENT_INSTRUCTION` (const `:194`, PLAN mode),
  `GIT_SHALLOW_CLONE_CONTEXT` via `_maybe_append_shallow_clone_context` (`:268`),
  and a `<HOST>{web_url}</HOST>` block (`:1773`).
- **Agent creation [EXTERNAL SDK]:**
  `configured_agent_settings = user.agent_settings.model_copy(update={'llm', 'tools',
  'mcp_config', 'agent_context': AgentContext(system_message_suffix=..., secrets=...)})`
  (`:1797`), then `agent = configured_agent_settings.create_agent()` (`:1808`).
- **System-prompt filename / kwargs override:** `_apply_server_agent_overrides(...)`
  (`:1833`, defined `:1402`): PLAN → `'system_prompt_planning.j2'` (`:1419`);
  DEFAULT → `{'cli_mode': False}` (`:1424`); applied via `agent.model_copy(...)` (`:1466`).
- **Hooks onto request:** `_load_hooks_from_workspace(...)` (`:1851`).
- **Confirmation / security policy** (see Step 6): selected here, POSTed to the agent-server.
- **Build request [EXTERNAL SDK]:**
  `request = conv_settings.create_request(StartConversationRequest, agent=agent, ...)` (`:1925`).
- **Skills onto request:** `_load_skills_onto_request(...)` (`:1931`) →
  `request.model_copy(update={'agent': updated_agent})` (`:1996`).

---

## Step 5 — Model request dispatched (turn starts)

**File:** `app_server/app_conversation/live_status_app_conversation_service.py`
**Symbol:** `_start_app_conversation` (`:361`), status `STARTING_CONVERSATION` (`:460`)
- Serialize with secrets exposed:
  `body_json = start_conversation_request.model_dump(mode='json', context={'expose_secrets': True})` (`:465`).
- Inject tracing user id: `body_json['user_id'] = laminar_user_id` (`:480`).
- **The turn is handed off [EXTERNAL agent-server]:**
  ```
  response = await self.httpx_client.post(
      f'{agent_server_url}/api/conversations',
      json=body_json,
      headers={'X-Session-API-Key': ...},
      timeout=self.sandbox_startup_timeout)         # :486
  info = ConversationInfo.model_validate(response.json())  # :509
  ```
- For a **follow-up message** on a running conversation, the equivalent dispatch is:
  `httpx_client.post(f'{agent_server_url}/api/conversations/{id}/events',
  json={'role', 'content', 'run'}, ...)`
  in `send_message_to_conversation` (`app_conversation_router.py:556`).

---

## Step 6 — [EXTERNAL] Streamed response, tool-call detection, permission check, tool execution, next iteration

**These occur inside the external agent-server / `openhands.sdk` agent loop. They are
NOT in this repo (unverified internal mechanics).** What this repo controls / observes:

**Permission / confirmation policy (selected here, enforced [EXTERNAL]):**
**File:** `app_server/app_conversation/app_conversation_service_base.py`
- Imports policy classes from `openhands.sdk.security` (`:39`–`:46`):
  `AlwaysConfirm`, `ConfirmRisky`, `NeverConfirm`, `LLMSecurityAnalyzer`,
  `SecurityAnalyzerBase`, `ConfirmationPolicyBase`.
- `_select_confirmation_policy(confirmation_mode, security_analyzer)` (`:677`):
  `False → NeverConfirm()` (`:682`); `True` + analyzer `'llm' → ConfirmRisky()` (`:686`);
  otherwise `AlwaysConfirm()` (`:688`).
- `_create_security_analyzer_from_string(...)` (`:652`): `'llm' → LLMSecurityAnalyzer()`.
- `_set_security_analyzer_from_settings(...)` (`:690`) →
  `POST {agent_server_url}/api/conversations/{id}/security_analyzer` (`:724`).
- Enforcement (confirm/deny gate, actual tool execution) happens **[EXTERNAL]**;
  this repo has no tool executor and no confirm/deny branch. (unverified internals)

**Loop shape [EXTERNAL] (unverified):** system prompt → `LLM.stream` → parse tool
calls (`ActionEvent`) → confirmation gate → execute tool → `ObservationEvent` →
feed back to the model → repeat until the model emits a final `MessageEvent`.
Each of these produces an `Event` that is POSTed back to `app_server` (Step 7).

---

## Step 7 — Event ingestion (tool calls, results, final response arrive back)

The agent-server pushes events back via a webhook. The callback URL is injected at
sandbox creation:
- `WEBHOOK_CALLBACK_VARIABLE = 'OH_WEBHOOKS_0_BASE_URL'`
  (`app_server/sandbox/sandbox_service.py:26`).
- Docker: set to `http://host.docker.internal:{host_port}/api/v1/webhooks`
  (`app_server/sandbox/docker_sandbox_service.py:419`).
- Remote: set to `{web_url}/api/v1/webhooks`
  (`app_server/sandbox/remote_sandbox_service.py:281`).

**File:** `app_server/event_callback/webhook_router.py`
**Symbol / handler:** `on_event` — `POST /webhooks/events/{conversation_id}` (`:468`)
- Auth: `valid_sandbox()` (`:250`, requires `X-Session-API-Key`) and
  `valid_conversation()` (`:296`).
- **Persist all events:**
  `asyncio.gather(*[event_service.save_event(conversation_id, event) for event in events])` (`:480`).
- Reconciliation:
  - `ConversationStateUpdateEvent` with `key=='stats'` → `process_stats_event` (`:486`).
  - `ObservationEvent` carrying `SwitchLLMObservation.active_model` → update
    conversation `llm_model` (`:499`–`:512`).
  - Terminal `execution_status` update → `update_execution_status` +
    `_track_conversation_terminal` (`:516`–`:532`).
- Fan out callbacks off the request path:
  `background_tasks.add_task(_run_callbacks_in_bg_and_close, conversation_id, created_by_user_id, events)` (`:534`).
- `_import_all_tools()` (`:630`, called at import `:640`) registers `openhands.tools`
  classes so embedded tool actions/observations deserialize correctly.

**Event kinds** are derived dynamically from all concrete SDK `Event` subclasses:
`EventKind = Literal[tuple(...get_known_concrete_subclasses(Event))]`
(`app_server/event_callback/event_callback_models.py:30`) — includes `MessageEvent`,
`ActionEvent`, `ObservationEvent`, `ConversationStateUpdateEvent` **[EXTERNAL]**.

---

## Step 8 — Persistence of events

**File:** `app_server/event/event_service.py`
**Symbol:** `EventService.save_event(conversation_id, event)` (`:61`) — the write path
(explicitly "not part of the REST api").

**File:** `app_server/event/event_service_base.py`
**Symbol:** `EventServiceBase` (`:32`)
- `save_event(...)` (`:190`) writes `{id_hex}.json` via `_store_event` (`:197`).
- Storage path: `get_conversation_path(...)` (`:66`) →
  `{prefix}/{user_id}/{V1_CONVERSATIONS_DIR}/{conversation_id.hex}`.
- Read/query: `get_event` (`:86`), `search_events` (`:94`, in-Python filter + sort),
  `count_events` (`:158`), `iter_events_for_export` (`:145`).

**Concrete backends (chosen by config):**
- `FilesystemEventService` — `_store_event` = `path.write_text(event.model_dump_json(...))`
  (`app_server/event/filesystem_event_service.py:33`).
- `AwsEventService` — S3 `put_object` (`app_server/event/aws_event_service.py:54`).
- `GoogleCloudEventService` — GCS blob write
  (`app_server/event/google_cloud_event_service.py:57`).
- Backend selected in `app_server/config.py:307`–`:327`
  (AWS→AWS, GCP→GCP, else Filesystem).

> Note: `app_server/event/event_store.py` is an **empty placeholder** (0 lines, nothing
> imports it — unverified intent). Events are stored by the `EventService`
> implementations, **not** through `file_store/` (which is a separate blob store for
> archives/settings/secrets; VERIFIED no `event/` file imports `file_store`).

---

## Step 9 — Callbacks (title generation, etc.)

**File:** `app_server/event_callback/webhook_router.py`
**Symbol:** `_run_callbacks_in_bg_and_close` (`:583`)
- For each event: `service.get_active_callbacks(...)` (`:603`) →
  `asyncio.gather(invoke_callback(...))` (`:606`) →
  `service.persist_callback_results(...)` (`:627`).
- Runs with **no DB connection held** during slow processors (pool-exhaustion mitigation).

**File:** `app_server/event_callback/sql_event_callback_service.py`
- `SQLEventCallbackService.get_active_callbacks` (`:204`) — SELECT active callbacks
  matching `conversation_id` + `event.kind`.
- `invoke_callback(...)` (`:284`) → `callback.processor(conversation_id, callback, event)` (`:294`).
- `persist_callback_results(...)` (`:226`) → tables `event_callback` /
  `event_callback_result`.

**File:** `app_server/event_callback/set_title_callback_processor.py`
- `SetTitleCallbackProcessor` (`:82`, `event_kind='MessageEvent'`, `:85`).
- On a `MessageEvent`, polls the agent-server for a generated title
  (`_poll_for_title`, `:37`), saves it onto `AppConversationInfo` (`:141`), then
  disables itself (`callback.status = DISABLED`; `save_event_callback`, `:151`).

---

## Step 10 — Pending / follow-up user input (next iteration input)

**File:** `app_server/pending_messages/pending_message_router.py`
**Symbol:** `queue_pending_message` — `POST '' ` (`:37`)
- Rate-limited at 10 (`count_pending_messages`, `:86`; 429 if ≥10).
- `pending_service.add_message(conversation_id, content, role)` (`:93`);
  `conversation_id` may be `task-{uuid}` so input can be queued **before** READY.

**File:** `app_server/pending_messages/pending_message_service.py`
**Symbol:** `SQLPendingMessageService` (`:76`)
- `add_message` (`:81`), `get_pending_messages` (`:122`, ordered by `created_at`),
  `update_conversation_id(old, new)` (`:168`, rewrites `task-{uuid}` → real UUID),
  `delete_messages_for_conversation` (`:151`).

**Delivery on READY:**
**File:** `app_server/app_conversation/live_status_app_conversation_service.py`
**Symbol:** `_process_pending_messages` (`:2199`, called at `:611` right after `READY`)
- `pending_message_service.update_conversation_id(task-..., real-uuid)` (`:2226`).
- `pending_message_service.get_pending_messages(...)` (`:2238`).
- Deliver each in order:
  `httpx_client.post(f'{agent_server_url}/api/conversations/{id}/events',
  json={'role','content','run': True}, ...)` (`:2256`) — same `/events` endpoint as
  `send-message`; this re-enters the **[EXTERNAL]** agent loop (Step 6).
- `pending_message_service.delete_messages_for_conversation(...)` (`:2273`).

---

## Step 11 — Final response / turn completion

- The final assistant `MessageEvent` and the terminal
  `ConversationStateUpdateEvent` (execution status) are produced **[EXTERNAL]** and
  arrive at `on_event` (Step 7), where:
  - The message is persisted like any other event (`save_event`).
  - Terminal status → `update_execution_status(...)` +
    `_track_conversation_terminal(...)` (`webhook_router.py:516`–`:532`).
- Clients read the completed turn via REST:
  **File:** `app_server/event/event_router.py`
  `search_events` (`GET /search`, `:29`), `count_events` (`GET /count`, `:70`),
  `batch_get_events` (`GET ''`, `:96`). **There is no SSE/WebSocket in app_server**;
  live streaming to the UI is against the **agent-server's own WebSocket** via the
  `conversation_url` handed to the client
  (documented at `app_conversation_router.py:453`–`:463`). (partly unverified — the
  agent-server WebSocket protocol is external.)
- Trajectory export: `open_conversation_export` →
  `iter_events_for_export` (`event_service_base.py:145`), streamed as a zip
  (`StreamingResponse`, `app_conversation_router.py:1638`).

---

## Summary table (turn stages → code)

| Stage | Where (this repo unless marked EXTERNAL) | Key symbol / call |
|---|---|---|
| User input | `app_conversation_router.py` / `pending_message_router.py` | `start_app_conversation` (`:365`), `send_message_to_conversation` (`:441`), `queue_pending_message` (`:37`) |
| Session creation | `live_status_app_conversation_service.py` | `start_app_conversation` (`:352`) → `_start_app_conversation` (`:361`) |
| Instruction/skill/hook/secret load | `app_conversation_service_base.py`, `skill_loader.py`, `hook_loader.py`, `conversation_secret_enricher.py` | `run_setup_scripts` (`:269`), `load_skills_from_agent_server` (`:505`), `load_hooks_from_agent_server` (`:103`) |
| System prompt / request build | `live_status_app_conversation_service.py` | `_build_start_conversation_request_for_user` (`:1630`), `create_agent()` (`:1808`), `create_request(...)` (`:1925`) |
| Model request dispatched | `live_status_app_conversation_service.py` | `POST /api/conversations` (`:486`) |
| Model stream / tool detect / permission / execute / iterate | **EXTERNAL agent-server** | (unverified internals); policy chosen by `_select_confirmation_policy` (`service_base.py:677`) |
| Event ingestion | `event_callback/webhook_router.py` | `on_event` (`:468`), `save_event` fan-out (`:480`) |
| Persistence | `event/event_service_base.py` + backends | `save_event` (`:190`), `_store_event` |
| Callbacks | `event_callback/sql_event_callback_service.py`, `set_title_callback_processor.py` | `get_active_callbacks` (`:204`), `SetTitleCallbackProcessor` (`:82`) |
| Next iteration / follow-up | `pending_messages/*`, `live_status_app_conversation_service.py` | `_process_pending_messages` (`:2199`) → `/events` |
| Final response read | `event/event_router.py` | `search_events` (`:29`) |

---

## Unverified / caveats

- **Everything inside the agent-server / `openhands.sdk` is not in this repo.** The
  system-prompt rendering, LLM streaming, tool-call detection, tool execution, and
  confirmation enforcement are reached only through the HTTP endpoints
  `POST /api/conversations`, `.../events`, `/api/skills`, `/api/hooks`,
  `/api/conversations/{id}/security_analyzer`. Their receiving-side behavior is
  **unverified** here.
- The default concrete `AppConversationService` is assumed to be
  `LiveStatusAppConversationService` (only implementation of the start-flow status
  machine found); the binding is resolved in `app_server/config.py` injectors
  (not fully read) — **unverified**.
- Real-time UI streaming uses the agent-server WebSocket (`conversation_url`);
  the protocol is external — **unverified**.
- `event/event_store.py` is empty; intent **unverified**.
- `mini-agent/` (separate package) has its own `PermissionPolicy` classes; no imports
  from `app_server` were found, so it appears unrelated to this flow — **unverified**.
