# Core Module Map — `openhands_all` (`app_server`)

A map of the core modules that participate in an agent turn, what each exports,
and how they depend on one another. Paths are relative to `openhands_all/`.

> **Boundary reminder (VERIFIED).** `app_server` is the **control plane**. The agent
> loop (model streaming, tool detection, tool execution, permission enforcement) runs
> in the **external `openhands-agent-server`** (using `openhands-sdk` /
> `openhands-tools`), which is **not vendored** in this repo. External symbols are
> tagged **[EXTERNAL]**. Uncertain items are tagged **(unverified)**.

The local package is a namespace package `openhands.app_server` (see
`__init__.py`, which extends `__path__` to co-exist with the external
`openhands.sdk` / `openhands.agent_server`).

---

## 1. HTTP / app assembly

| File | Key exports | Role |
|---|---|---|
| `app_server/app.py` | `app` (`FastAPI`), `combine_lifespans` | Builds the FastAPI app; mounts `v1_router`, health router, `/mcp`; adds CORS / cache / rate-limit middleware. |
| `app_server/v1_router.py` | `router` (`APIRouter(prefix='/api/v1')`) | Aggregates all sub-routers: event, app-conversation, pending-message, sandbox, settings, secrets, user, skills, **webhook**, web-client, git, config. |
| `app_server/config.py` | `AppServerConfig`, `get_*_service`, `depends_*` | Central DI/config. Chooses concrete injectors for `event`, `event_callback`, etc. (e.g. Filesystem/AWS/GCP event service, `config.py:307`–`:330`). |
| `app_server/shared.py` | `SettingsStoreImpl`, shared singletons | Resolves concrete implementations used across the app. |
| `app_server/middleware.py` | CORS / auth / rate-limit middleware | Request-level auth (`SetAuthCookieMiddleware`) and limits. |
| `app_server/errors.py` | `OpenHandsError`, `PermissionsError` | Generic HTTP/auth errors (not tool-permission). |
| `app_server/constants.py` | `validate_secret_name`, dir constants | Shared validation + path constants (`V1_CONVERSATIONS_DIR`, etc.). |
| `server/*` | `server/app.py`, `server/listen.py`, `server/__main__.py` | Process bootstrap / ASGI entry (wraps `app_server.app`). |

---

## 2. App-conversation (session lifecycle) — `app_server/app_conversation/`

| File | Key exports | Role |
|---|---|---|
| `app_conversation_router.py` | `router`; handlers `start_app_conversation` (`:365`), `send_message_to_conversation` (`:441`), `stream_app_conversation_start` (`:1022`), `_consume_remaining` (`:1659`) | REST surface for starting conversations and sending user input; proxies user input to agent-server `/events`. |
| `app_conversation_service.py` | `AppConversationService` (ABC, `:33`), `AppConversationServiceInjector` (`:192`) | Abstract service contract; defines `start_app_conversation` generator + status doc. |
| `app_conversation_service_base.py` | `AppConversationServiceBase` (`:91`), `get_project_dir` (`:56`), `run_setup_scripts` (`:269`), `clone_or_init_git_repo` (`:342`), `maybe_setup_git_hooks` (`:557`), `load_and_merge_all_skills` (`:100`), `_select_confirmation_policy` (`:677`), `_create_security_analyzer_from_string` (`:652`) | Shared start-flow logic: repo clone, setup script, git hooks, skill merge, condenser/security policy selection. |
| `live_status_app_conversation_service.py` | `LiveStatusAppConversationService` (`:240`), `_start_app_conversation` (`:361`), `_build_start_conversation_request_for_user` (`:1630`), `_configure_llm` (`:1215`), `_setup_conversation_secrets` (`:1179`), `_process_pending_messages` (`:2199`) | **The orchestrator.** Runs the status machine, assembles the `Agent` + `StartConversationRequest`, POSTs to agent-server, delivers pending messages. |
| `app_conversation_models.py` | `AppConversationStartRequest` (`:221`), `AppConversationStartTask` (`:307`), `AppConversationInfo` (`:110`), `AppConversation` (`:195`), `AppConversationStartTaskStatus` (`:288`), `AgentType` (`:64`), `AppSendMessageRequest` (`:376`) | Request/response + persisted models and the status enum. |
| `app_conversation_start_task_service.py` | `AppConversationStartTaskService` (ABC, `:15`), `...Injector` (`:73`) | Contract for storing start-task rows. |
| `sql_app_conversation_start_task_service.py` | `SQLAppConversationStartTaskService` (`:78`), `StoredAppConversationStartTask` (`:54`), `save_app_conversation_start_task` (`:235`) | SQL persistence of each status transition (table `app_conversation_start_task`). |
| `app_conversation_info_service.py` / `sql_app_conversation_info_service.py` | `AppConversationInfoService`, `SQLAppConversationInfoService` | Persist/read `AppConversationInfo` (title, llm_model, tags, execution status). |
| `skill_loader.py` | `load_skills_from_agent_server` (`:505`), `build_org_configs` (`:273`), `build_sandbox_config` (`:485`), `authenticate_marketplace_sources` (`:425`), `SkillInfo` (`:53`) | Proxy to agent-server `POST /api/skills`; converts to `Skill` **[EXTERNAL]**. |
| `hook_loader.py` | `load_hooks_from_agent_server` (`:103`), `fetch_hooks_from_agent_server` (`:43`), `get_project_dir_for_hooks` (`:19`) | Proxy to agent-server `POST /api/hooks`; returns `HookConfig` **[EXTERNAL]**. |
| `conversation_secret_enricher.py` | `ConversationSecretEnricher` (`:21`), `ConversationSecretEnrichment` (`:15`) | Build-time secret enrichment extension point (no-op in this repo). |
| `git/pre-commit.sh` | (shell shim) | Uploaded to sandbox `.git/hooks/pre-commit`; sources `.openhands/pre-commit.sh`. |
| `git/README.md` | (docs) | Notes the directory holds git-config files. |

---

## 3. Pending messages — `app_server/pending_messages/`

| File | Key exports | Role |
|---|---|---|
| `pending_message_router.py` | `router`; `queue_pending_message` (`:37`) | Queue user input (rate-limited 10); accepts `task-{uuid}` before READY. |
| `pending_message_service.py` | `PendingMessageService` (ABC, `:41`), `SQLPendingMessageService` (`:76`), `StoredPendingMessage` (`:27`), `update_conversation_id` (`:168`) | Persist/queue user input; migrate `task-` id → real conversation UUID. |
| `pending_message_models.py` | `PendingMessage` (`:12`), `PendingMessageResponse` (`:27`) | Wire models. |

---

## 4. Events (ingestion + storage) — `app_server/event/`

| File | Key exports | Role |
|---|---|---|
| `event_service.py` | `EventService` (ABC, `:18`), `save_event` (`:61`), `search_events` (`:26`), `EventServiceInjector` (`:73`) | Read/query + internal write contract for conversation events. |
| `event_service_base.py` | `EventServiceBase` (`:32`), `get_conversation_path` (`:66`), `save_event` (`:190`), `iter_events_for_export` (`:145`) | Path-prefix-scoped storage base; in-Python filter/sort/paginate. |
| `filesystem_event_service.py` | `FilesystemEventService` (`:18`), `FilesystemEventServiceInjector` (`:45`) | Local-disk JSON event store (default). |
| `aws_event_service.py` | `AwsEventService` (`:28`), `AwsEventServiceInjector` (`:94`) | S3-backed event store. |
| `google_cloud_event_service.py` | `GoogleCloudEventService` (`:38`), `GoogleCloudEventServiceInjector` (`:73`) | GCS-backed event store. |
| `event_router.py` | `router`; `search_events` (`:29`), `count_events` (`:70`), `batch_get_events` (`:96`) | Read-only REST for events (no SSE/WebSocket). |
| `event_store.py` | (empty) | Placeholder, 0 lines, unused (unverified intent). |

---

## 5. Event callbacks (fan-out) — `app_server/event_callback/`

| File | Key exports | Role |
|---|---|---|
| `webhook_router.py` | `router`; `on_event` (`:468`), `on_conversation_update` (`:348`), `get_secret` (`:553`), `valid_sandbox` (`:250`), `valid_conversation` (`:296`), `_run_callbacks_in_bg_and_close` (`:583`), `_import_all_tools` (`:630`) | **Inbound webhook** the agent-server POSTs events to; persists events + reconciles status + fans out callbacks; serves runtime git secrets. |
| `event_callback_service.py` | `EventCallbackService` (ABC, `:16`), `execute_callbacks` (`:61`), `get_active_callbacks` (`:65`), `EventCallbackServiceInjector` (`:87`) | Callback CRUD + execution contract. |
| `sql_event_callback_service.py` | `SQLEventCallbackService` (`:92`), `StoredEventCallback` (`:48`), `StoredEventCallbackResult` (`:76`), `invoke_callback` (`:284`) | SQL persistence + execution of callbacks (short-lived sessions). |
| `event_callback_models.py` | `EventCallbackProcessor` (ABC, `:40`), `EventCallback` (`:90`), `CreateEventCallbackRequest` (`:79`), `EventKind` (`:30`), `LoggingCallbackProcessor` (`:57`) | Processor base + models; `EventKind` derived from all SDK `Event` subclasses **[EXTERNAL]**. |
| `event_callback_result_models.py` | `EventCallbackResult` (`:21`), `EventCallbackResultStatus` (`:11`) | Callback result models. |
| `set_title_callback_processor.py` | `SetTitleCallbackProcessor` (`:82`), `_poll_for_title` (`:37`) | Generates + sets conversation title after first `MessageEvent`, then self-disables. |
| `util.py` | `get_agent_server_url_from_sandbox` (`:44`), `ensure_running_sandbox` (`:30`), `ensure_conversation_found` (`:21`) | Helpers to resolve the agent-server URL from sandbox exposed URLs. |
| `__init__.py` | re-exports `EventCallbackProcessor`, `LoggingCallbackProcessor` | Registers processors for discriminated-union deserialization. |

---

## 6. Sandbox (runtime provisioning) — `app_server/sandbox/`

| File | Key exports | Role |
|---|---|---|
| `sandbox_service.py` | `SandboxService`, `WEBHOOK_CALLBACK_VARIABLE = 'OH_WEBHOOKS_0_BASE_URL'` (`:26`) | Contract for starting/waiting/resuming sandboxes; injects the webhook callback env var. |
| `docker_sandbox_service.py` | `DockerSandboxService`; sets webhook URL (`:419`) | Local Docker sandbox implementation. |
| `remote_sandbox_service.py` | `RemoteSandboxService`; sets webhook URL (`:281`) | Remote/hosted sandbox implementation. |
| `sandbox_models.py` | `SandboxInfo`, exposed-URL models | Sandbox metadata; exposed URLs include the `AGENT_SERVER` endpoint. |

---

## 7. Settings (LLM / agent config source) — `app_server/settings/`

| File | Key exports | Role |
|---|---|---|
| `settings_models.py` | `Settings` (`:347`), `AgentSettingsConfig` (via SDK), `to_agent_settings` (`:704`), `conversation_settings` (`:377`) | Persisted user settings: LLM, agent, mcp, condenser, `confirmation_mode`, `security_analyzer`, disabled skills, marketplaces. |
| `settings_store.py` | `SettingsStore` (ABC, `:8`), `load(resolve_agent_profile=...)` (`:22`) | Load/store settings; `resolve_agent_profile=True` returns the effective launch view used at conversation start. |
| `file_settings_store.py` | `FileSettingsStore` (`:12`) | OSS file-backed settings store (`settings.json`). |
| `llm_profiles.py` | `LLMProfiles` (`:137`), `resolve_profile_llm` (`:37`) | Named LLM profiles; `resolve_profile_llm` forces `stream=True`. |
| `agent_profiles.py` | `AgentProfiles` (`:64`) | Cloud agent-profile store (references an LLM profile). |
| `marketplace_composition.py` | `compose_marketplaces` (`:206`), `load_composed_marketplaces` (`:254`) | Instance/org/user marketplace precedence for skill sources. |
| `settings_router.py` | `router` | REST for settings + profile mutations (not exhaustively read — unverified). |

---

## 8. Secrets / git / user context — supporting modules

| File / dir | Key exports | Role |
|---|---|---|
| `app_server/secrets/` | secret storage services | Persisted user/provider secrets (distinct from build-time enrichment). |
| `app_server/git/` | git provider helpers | Authenticated git URL resolution, provider routing. |
| `app_server/user_auth/` + `app_server/user/` | `UserContext`, `get_authenticated_git_url`, `get_user_info` | Identity + per-provider credentials feeding clone/skills/secrets. |
| `app_server/utils/git.py` | `ensure_valid_git_branch_name`, `replace_localhost_hostname_for_docker` | Git branch validation + docker host rewriting for agent-server URLs. |
| `app_server/services/` | `injector.py` (`Injector`), `db_session.py`, `httpx_client_injector.py`, `jwt_service.py` | DI primitives, DB sessions, shared httpx client, JWT for secret lookup. |
| `app_server/file_store/` | `FileStore` (`files.py:8`), `LocalFileStore`, `S3FileStore`, `GoogleCloudFileStore`, `get_file_store` (`__init__.py:8`) | Generic blob store for archives/settings/secrets — **separate** from event storage. |
| `app_server/status/` | `status_router` (`GET /alive|/health|/ready|/server_info`), `system_stats.py` (legacy V0) | Server health probes (NOT conversation/agent run status). |
| `app_server/mcp/` | MCP server app (`mcp_server.http_app`) | Mounted at `/mcp`; exposes an MCP endpoint the agent's MCP client points to. |
| `analytics/` | `analytics_service.py`, `track_conversation_created`, `_track_conversation_terminal` usage | Conversation lifecycle analytics. |

---

## 9. External dependencies (not in this repo) — [EXTERNAL]

| Package | Symbols used here | Where it matters in a turn |
|---|---|---|
| `openhands.sdk` | `Agent`, `AgentContext`, `LLM`, `LocalWorkspace`, `HookConfig`, `MCPServer`, `PluginSource`, `LookupSecret`, `StaticSecret`, `ACPAgentSettings`, `SwitchLLMTool`, `AgentSettings.create_agent()`, `ConversationSettings.create_request()`, `Event`/`ActionEvent`/`ObservationEvent`/`MessageEvent`/`ConversationStateUpdateEvent`, `openhands.sdk.security` policies, `openhands.sdk.skills.Skill` | Agent construction, request build, event schemas, confirmation policy classes. |
| `openhands.tools` | `get_default_tools`, `register_builtins_agents`, `get_planning_tools`, `get_registered_agent_definitions` | Tool set attached to the agent. |
| `openhands.agent_server` | `StartConversationRequest`, `SendMessageRequest`, `ConversationInfo`, `TextContent`; HTTP API `/api/conversations`, `/events`, `/api/skills`, `/api/hooks`, `/api/conversations/{id}/security_analyzer` | **Runs the actual agent turn** and POSTs events back to the webhook. |
| `AsyncRemoteWorkspace` (`openhands.sdk.workspace.remote.async_remote_workspace`) | `execute_command`, `file_upload`, `file_download` | Sandbox filesystem ops during setup. |

---

## Dependency direction (per turn)

```
Client
  → app.py / v1_router.py
    → app_conversation_router.py            (accept request / user input)
      → live_status_app_conversation_service.py   (orchestrate)
        → app_conversation_service_base.py   (clone/setup/hooks/skills/policy)
        → skill_loader.py / hook_loader.py   (→ agent-server /api/skills, /api/hooks)
        → settings/* + secrets/* + git/*     (config inputs)
        → sandbox/*                          (provision runtime + inject webhook URL)
        → [EXTERNAL] POST /api/conversations (dispatch turn)
        → sql_app_conversation_start_task_service.py  (persist status)

[EXTERNAL agent-server runs the loop]
  → POST /api/v1/webhooks/events/{id}
    → event_callback/webhook_router.py::on_event
      → event/event_service*.py            (persist events)
      → event_callback/sql_event_callback_service.py  (run callbacks)
        → set_title_callback_processor.py   (title)

Client reads:
  → event/event_router.py                  (REST search/count/batch-get)
```

---

## Unverified / caveats

- The default binding of `AppConversationService` to
  `LiveStatusAppConversationService` is inferred from it being the only start-flow
  implementation; the actual wiring is in `config.py` injectors (not fully read).
- `settings_router.py` endpoints were not exhaustively read.
- `event_store.py` is empty and unused (intent unverified).
- All `[EXTERNAL]` module internals are outside this repo and unverified.
- `mini-agent/` is a separate package with its own permission model and is not
  imported by `app_server` (appears unrelated to this flow — unverified).
