# Backend Code Architecture

## 1. Purpose

This document defines how backend code is organized for Nasus V1 and how the
current codebase should continue migrating toward DDD without breaking the
running product.

The product domains are fixed:

- `system_image`: source registration, ingestion, context materialization,
  baseline/branch, retrieval, embedding, and rerank.
- `agent`: conversation, AgentGoal, AgentStep, memory, planner, and swarm.
- `quality_loop`: US work, quality asset pack, run, evidence, failure analysis,
  release readiness, and release decision.
- `platform`: auth/RBAC, settings, tool catalog, ToolInvocation, governance
  gates, audit, and SSE outbox.

## 2. Target Package Structure

```text
apps/api/app/
  bootstrap/
    container.py           # explicit process-local application container
  interface/
    http/                 # FastAPI routers and HTTP error mapping
    sse/                  # SSE envelopes and streaming adapters
  application/
    system_image/         # use cases and ports
    agent/
    quality_loop/
    platform/
  domain/
    system_image/         # pure entities, value objects, policies
    agent/
    quality_loop/
    platform/
    shared/
  infrastructure/
    config/               # runtime environment validation
    persistence/          # SQLAlchemy models and repository adapters
    llm/                  # LLM, embedding, rerank providers
    storage/              # MinIO/S3 adapters
    workflow/             # Temporal/LangGraph gateways
    runner/               # execution runner adapters
  composition.py          # FastAPI construction and middleware/router wiring
  store.py                # temporary RuntimeAssembly host + compatibility facade
```

## 3. Dependency Direction

Allowed dependency flow:

```text
interface -> application -> domain
composition -> bootstrap -> application + infrastructure
interface -> bootstrap container (service resolution only)
infrastructure -> application/domain through ports
```

Rules:

- `composition.py` and workflow workers must resolve services through
  `bootstrap/ApplicationContainer`; they must not import the global `store`.
- `ApplicationContainer` resolves the process-local `RuntimeAssembly`, never
  `ApplicationRuntime`. The compatibility wrapper shares that same assembly and
  must not create a parallel repository/event/provider graph.
- `ApplicationContainer` exposes application services only. It must not expose
  `ApplicationStore`, compatibility dictionaries, repositories, ORM sessions,
  or infrastructure clients to HTTP/Temporal adapters.
- Compatibility runtime initialization is lazy and may occur only inside the
  bootstrap factory after production runtime validation. Importing `store.py`
  must not connect to PostgreSQL, hydrate projections, or seed data.
- `interface` must not import the global `store`.
- Therefore, interface must not import the global `store`. HTTP routers receive
  application services through typed dependency aliases from
  `interface/http/dependencies.py`; only that dependency module may read
  `request.app.state`.
- HTTP command request bodies must be explicit application DTOs. Routers must
  not accept raw `dict` payloads and parse business fields inline; validation
  belongs in DTOs and application services.
- `domain` must not import FastAPI, SQLAlchemy, object storage, LLM clients,
  Temporal, LangGraph, or environment configuration.
- `domain` may import Python standard library modules and other domain modules
  through relative imports; use `Protocol` inputs instead of concrete API DTO,
  ORM, repository, or compatibility-store types.
- Cross-domain calls go through application services or declared ports.
- Database transactions and external side effects are application or
  infrastructure concerns, not domain concerns.
- All user-visible write actions must remain traceable through
  `ToolInvocationRuntime`.
- Liveness and readiness are separate contracts. The HTTP layer may only call
  `ReadinessApplicationService`; SQLAlchemy and S3 checks are implemented by
  infrastructure probes assembled by `bootstrap/container.py`.
- Mandatory runtime dependencies must fail readiness independently. A healthy
  API process must not receive production traffic when PostgreSQL or MinIO/S3
  is unavailable.
- HTTP request correlation, low-cardinality Prometheus metrics, and rate-limit
  classification belong to the platform delivery boundary. The application
  layer exposes `RequestRateLimitPort`; the production adapter persists atomic
  fixed windows in PostgreSQL. Routers must not implement process-local
  counters or derive their own request IDs.
- Every response carries `X-Request-ID`. Supplied IDs are accepted only when
  they match the bounded safe character set; otherwise the interface creates a
  new opaque ID. The same ID is bound to the actor context, error envelope,
  structured request log, Temporal workflow payload, and HTTP metrics context.
- Production rate limiting is fail-closed. Authentication endpoints are keyed
  by the direct client address, authenticated API and Agent writes by user ID.
  Reverse-proxy forwarding headers are not trusted until a deployment defines
  an explicit trusted-proxy boundary.
- System-image application services depend on `SourceIngestionPort`, never on
  filesystem or Git implementations. `GitSourceConnector` belongs under
  `infrastructure/system_image`; its managed checkout path and provider details
  are adapter state, while commit revision and evidence references cross the
  port as stable facts.

## 4. Current Transitional State

The current codebase is intentionally transitional:

- The DDD directory skeleton exists.
- HTTP routers resolve typed application services from `ApplicationContainer`.
- The Temporal worker resolves `AgentWorkflowActivityApplicationService` from
  the same container and does not import or dynamically inspect `ApplicationStore`.
- `AgentApplicationService` and `PlatformApplicationService` receive explicit
  subservice dependencies; they no longer discover collaborators from Store
  attributes.
- `ProjectWorkspaceApplicationService` receives explicit read, authorization,
  tool-invocation, and conversation ports. HTTP workspace reads use
  `SQLAlchemyProjectWorkspaceReadModel` and query PostgreSQL directly; they no
  longer refresh or consume the compatibility projection dictionaries.
- `ToolInvocationRuntime` receives explicit state, catalog, authorization,
  governance, audit, Agent-reply, event, and handler-registry ports. Runtime
  lifecycle policy no longer retains `ApplicationStore` or constructs its own
  application services. The projected-state and static-catalog adapters live
  under `infrastructure/platform`, while handler assembly remains in the
  composition root.
- `ApplicationStore` remains a compatibility projection/composition runtime for
  legacy behavior, but it is hidden behind bootstrap and lazily initialized.
  New interface or workflow code must never receive it.
- `auth.py`, `auth_service.py`, `database.py`, `db_models.py`, `repositories.py`,
  `settings_store.py`, `runtime_config.py`, `agent_runtime_config.py`,
  `object_storage.py`, `llm.py`, `run_orchestrator.py`,
  `system_image_service.py`,
  `source_ingestion.py`, `context_extraction.py`,
  `conversation_orchestrator.py`,
  `system_image_tool_catalog.py`,
  `agent_graph_runtime.py`, `tool_invocation_runtime.py`,
  `tool_invocation_handlers.py`, `system_image_tool_handlers.py`,
  `project_version_tool_handlers.py`, `quality_loop_tool_handlers.py`,
  `governance_tool_handlers.py`, `query_tool_handlers.py`,
  `temporal_agent_gateway.py`, and
  `langgraph_agent_gateway.py` at the app root are compatibility re-export
  modules only. HTTP authentication request parsing and error response mapping
  live under `interface/http/auth.py`; the real SQLAlchemy engine/session/Base,
  ORM records, unit-of-work helper, repository adapters, and settings
  persistence adapter live under `infrastructure/persistence`; runtime environment validation and
  Temporal/LangGraph gateway env config live under `infrastructure/config`;
  real object storage adapters live under `infrastructure/storage`; real
  LLM/embedding/rerank provider adapters live under `infrastructure/llm`; real
  execution runner adapters live under `infrastructure/runner`; real
  Temporal/LangGraph workflow gateways and workflow workers live under
  `infrastructure/workflow`.
- `models.py` is a compatibility re-export barrel only. It must not define
  Pydantic models, domain objects, request DTOs, response DTOs, or cross-domain
  read models. Internal backend code must import contracts from the owning
  bounded-context modules instead of importing from the app-root barrel.
- App-root modules are not implementation homes. Except for `main.py`,
  `composition.py`, `store.py`, and the transitional `models.py` compatibility
  barrel, every `apps/api/app/*.py` file must remain a tiny relative
  `import *` compatibility re-export. New classes, functions, environment
  reads, ORM queries, HTTP request parsing, LLM calls, object storage calls,
  workflow adapters, and business rules must be added under the owning
  `interface`, `application`, `domain`, or `infrastructure` package first.
- `agent_runtime_models.py` at the app root is a compatibility re-export only.
  The real Agent planning value objects live in `domain/agent/runtime_models.py`
  and should be imported from the domain package by planners, orchestrators,
  workflow gateways, and graph runtimes.
- `agent_goal_state_machine.py` at the app root is a compatibility re-export
  only. The real AgentGoal/AgentStep lifecycle policy lives in
  `domain/agent/state_machine.py` and must use protocol-shaped inputs instead
  of importing API DTOs from `models.py`.
- `agent_loop_runtime.py` at the app root is a compatibility re-export only.
  The real AgentGoal runtime application orchestration lives in
  `application/agent/loop.py`; it owns goal creation, audit/event emission, and
  graph runtime delegation.
- `agent_graph_runtime.py` at the app root is a compatibility re-export only.
  The real AgentGoal graph runtime contract and Local/LangGraph wrappers live
  in `application/agent/graph.py`; environment-based graph runtime selection
  and LangGraph gateway assembly live in
  `infrastructure/workflow/agent_graph_factory.py`.
- `agent_workflow_runtime.py` at the app root is a compatibility re-export
  only. Workflow runtime protocols and Local/Temporal wrappers live in
  `application/agent/workflow.py`; environment-based runtime selection and
  Temporal gateway assembly live in `infrastructure/workflow/agent_workflow_factory.py`.
- `agent_goal_plan_compiler.py` at the app root is a compatibility re-export
  only. The real AgentGoal proposal-to-tool-plan compiler lives in
  `application/agent/plans.py` because it reads current project/system-image
  state and validates against the tool catalog.
- `agent_planner.py` at the app root is a compatibility re-export only. The
  real deterministic and LLM-structured planner lives in
  `application/agent/planner.py` because it maps conversation input plus memory
  context into clarification, direct answer, tool plan, or AgentGoal decisions.
  Planner context and state compilation receive
  `AgentPlannerContextAdapters`, `AgentPlanningProjectionState`, and
  `AgentPlanningRuntimeAdapters`; their infrastructure adapters must not retain
  `ApplicationStore`.
- `agent_swarm.py` at the app root is a compatibility re-export only. The real
  bounded sub-agent assignment and merge coordinator lives in
  `application/agent/swarm.py` because it persists swarm runs and emits
  conversation events. Production `SQLAlchemyAgentSwarmState` writes and reads
  swarm runs plus worker assignments directly through `ConversationRepository`;
  production composition must not maintain an `ApplicationStore.agent_swarms`
  mirror or hydrate one at startup.
- `AgentMemoryContext`, `memory_context_hash`, and `memory_context_summary`
  live in `domain/agent/memory.py`. Store-backed memory context assembly,
  system-image memory retrieval, and retrieval tracing live in
  `application/agent/memory.py` as `AgentMemoryManager`. Memory item queries
  used by Agent read models also belong to `AgentMemoryManager`; compatibility
  callers use `ApplicationStore.list_agent_memory_items`, which delegates to
  the PostgreSQL-backed Agent memory state. Production composition has no
  `ApplicationStore.agent_memory_items` or `agent_memory_links` projections. The root
  `agent_memory.py` module is compatibility-only and must not regain manager
  implementation. System-image memory context sections and long-term
  system-image refs must be delegated to
  `SystemImageMemoryContextApplicationService`; Agent memory must not directly
  read baselines, raw assets, knowledge objects, context relationships, or
  metric snapshots. System-image retrieval trace writes must be delegated to
  `SystemImageRetrievalTraceApplicationService`; Agent memory must not create
  `RetrievalRun` records, append retrieval runs, or calculate system-image
  baseline, embedding, rerank, or fallback metadata inline.
- `runtime_config.py` at the app root is a compatibility re-export only. The
  real startup environment guard lives in `infrastructure/config/runtime_config.py`
  because it reads deployment environment variables and validates infrastructure
  wiring before the store is imported.
- `agent_runtime_config.py` at the app root is a compatibility re-export only.
  Temporal and LangGraph gateway env configuration lives in
  `infrastructure/config/agent_runtime_config.py`.
- The first extracted application services delegate to `ApplicationStore`, but
  they establish the correct interface boundary.
- System-image compatibility workspaces receive explicit
  `SystemImageProjectionState` / `SystemImageWorkspaceAdapters` during the
  remaining migration. Production quality-loop composition uses only the
  `SQLAlchemy*Workspace` adapters and canonical repositories;
  `QualityLoopProjectionState` / `QualityLoopWorkspaceAdapters` are
  legacy-test fixtures and must not be assembled by `ApplicationStore`.
  Neither bounded context may retain `ApplicationStore`.
- `tests/test_ddd_boundaries.py` enforces backend import direction with an AST
  import-boundary scan: `domain` must not import `application`,
  `infrastructure`, or `interface`; `application` must not import `interface`;
  `interface` must not import `infrastructure` directly. Add an application
  service, domain policy input, or infrastructure adapter when a new dependency
  is needed instead of bypassing the layer boundary.

This is acceptable only as a migration state. New business logic should not make
the compatibility facade larger.

## 5. Application Service Contracts

Application services are the public backend use-case surface for routers.

Current services:

- `AgentApplicationService`: conversation management, message handling,
  AgentGoal lifecycle, Agent memory context queries/checkpoints, Agent event
  streams, and swarm event streams. Agent-owned runtime helpers, including
  system-image materialization swarm startup, must live behind this application
  boundary. This service is a HTTP-facing facade: it composes dedicated
  application services such as `ConversationManagementApplicationService`,
  `ConversationMessageApplicationService`,
  `AgentGoalLifecycleApplicationService`, `AgentMemoryManager`,
  `AgentSwarmCoordinator`, and `PlatformEventApplicationService`; it must not
  keep a `self._store` escape hatch or call `ApplicationStore` lifecycle,
  stream, or swarm methods directly.
- `application/agent/agent_models.py`: Agent application contract types for
  `SpaceType`, `ConversationSession`, `ConversationMessage`,
  `ConversationSummaryCheckpoint`, `ConversationLink`,
  `SessionKnowledgeBinding`, `AgentGoal`, `AgentStep`, `AgentMemoryItem`,
  `AgentMemoryLink`, `AgentSwarmRun`, `AgentWorkerAssignment`, and the
  conversation/Agent request DTOs. App-root `models.py` may re-export these
  names during migration, but Agent application services, workflow adapters,
  persistence adapters, HTTP Agent/conversation routes, and system-image
  retrieval ports must import them from this contract. Do not add new
  Agent/conversation DTOs to the global model bucket.
- `AgentGoalLifecycleApplicationService`: AgentGoal lifecycle coordination
  above the concrete workflow runtime: active-goal guard, manual creation,
  canonical AgentGoal record creation, default step construction, goal
  read/checkpoint projection, existence checks, resume, interrupt, feedback,
  and active-goal lookup. The root `agent_service.py`
  module is a compatibility alias only, and `ApplicationStore.create_agent_goal`
  is a compatibility delegate only. Neither surface should construct
  `AgentGoal` / default `AgentStep` records directly or regain lifecycle
  branching. `ApplicationStore.get_agent_goal` and
  `ApplicationStore.get_agent_goal_checkpoint` are compatibility delegates only;
  goal lookup and checkpoint projection must stay behind
  `AgentGoalLifecycleApplicationService`, not direct `agent_goals` reads or
  workflow-runtime calls from the store facade. Lifecycle event publication must go through
  `PlatformEventApplicationService`; do not call
  `ApplicationStore._push_event` or `ApplicationStore._push_goal_event`
  directly from this service.
- `AgentGoalProjectionApplicationService`: AgentGoal-to-conversation projection
  writer. It is responsible for upserting `AgentGoal` facts into the
  `ConversationSession.agent_goals` read model and persisting the conversation
  projection. Lifecycle, graph runtime, message orchestration, and Temporal
  workflow sinks must use this service. `ApplicationStore._upsert_goal_in_conversation`
  is only a compatibility delegate and must not contain projection rules.
  During the compatibility phase, `ApplicationStore` must hold a
  constructor-injected `agent_goal_projection` instance and delegate to it
  directly; it must not instantiate this service inside projection methods.
- AgentGoal projection, lifecycle, and outer-loop infrastructure adapters must
  receive explicit dependency records from
  `infrastructure/agent/goal_state_dependencies.py`:
  `AgentGoalProjectionState`, `AgentGoalLifecycleState`,
  `AgentGoalProjectionPersistenceAdapters`, `AgentGoalLifecycleAdapters`, and
  `AgentLoopRuntimeAdapters`. Projection state must not require lifecycle-only
  dictionaries; audit, message, SSE, repository, and Agent service calls are
  injected individually. These adapters must not retain `ApplicationStore` or
  resolve collaborators through Store attributes after construction.
  `infrastructure/agent/application_port_dependencies.py` defines the outer
  `AgentApplicationProjectionState`, `AgentApplicationPersistenceAdapters`,
  and `AgentApplicationRuntimeAdapters` records. The compatibility Store may
  assemble these records at the composition root, but
  `LegacyAgentApplicationPorts` receives only those records and never the
  Store itself, until composition moves fully to `composition.py`.
- The main conversation runtime adapter receives
  `AgentConversationRuntimeAdapters`. It translates the conversation
  application port to explicitly injected Planner, ToolInvocation, AgentGoal,
  governance, projection, and audit commands instead of retaining
  `ApplicationStore`.
- Conversation message state, summary checkpoints, SSE event publication, and
  AgentGoal explanation queries use explicit infrastructure dependency records:
  `AgentConversationProjectionState`,
  `AgentConversationPersistenceAdapters`,
  `AgentConversationCheckpointAdapters`, `AgentConversationEventAdapters`, and
  `AgentGoalExplanationAdapters`. The compatibility Store may compose these
  records while migration is in progress, but the adapters themselves may not
  retain Store, discover repositories dynamically, or construct platform event
  services.
- Conversation management infrastructure uses
  `AgentConversationManagementProjectionState`,
  `AgentConversationManagementPersistenceAdapters`, and
  `AgentConversationManagementRuntimeAdapters`. The adapter must not retain
  `ApplicationStore`. `ProjectScopeResolutionApplicationService` depends on
  `ProjectScopeReadPort`. Production composition uses
  `infrastructure/platform/SQLAlchemyProjectScopeReadModel` so project,
  version, and US ownership is read from PostgreSQL in both API and workflow
  worker processes. `CompatibilityProjectScopeProjection` is
  test/migration-only.
- `ConversationLink` is a durable Agent collaboration fact, not an in-memory
  UI convenience. Merge/link operations write `ConversationLinkRecord` through
  `ConversationRepository`; API and worker reads load it from PostgreSQL and
  production composition must not recreate a process-local link projection.
- `AgentGoalExplanationApplicationService`: AgentGoal explanation read-model
  assembly for UI/API consumers. It owns current/blocked step projection,
  waiting reason, next action, reasoning summary, memory refs, tool invocation
  refs, and audit refs. Keep this read-side service separate from lifecycle
  commands. It must obtain AgentGoal state and checkpoint projection through
  `AgentGoalLifecycleApplicationService` instead of direct `agent_goals` reads
  or workflow-runtime calls; `ApplicationStore.get_agent_goal_explanation` is a compatibility
  delegate only. AgentGoal explanation memory refs must be read through
  `AgentMemoryManager` via `ApplicationStore.list_agent_memory_items`; memory
  facts are loaded from PostgreSQL rather than a process-local projection.
  Agent application services must obtain ToolInvocation facts through
  the platform ToolInvocation application boundary
  (`ApplicationStore.get_tool_invocation` and
  `ApplicationStore.list_tool_invocations` compatibility delegates during
  migration), not by reading `ApplicationStore.tool_invocations` directly.
- `AgentGoal` is a PostgreSQL-only runtime fact. API and Temporal worker
  processes use `ConversationRepository` for lifecycle reads and writes;
  distributed result synchronization performs an idempotent repository upsert
  before refreshing the remaining project read model. Store must not maintain
  an independent AgentGoal or Conversation dictionary.
- `ConversationMessageApplicationService`: main conversation message
  orchestration for user messages. It owns source-binding replies, confirmation
  dispatch, planner decision routing, AgentGoal startup, tool invocation
  creation, and query-answer fallback dispatch. Confirmation-driven AgentGoal
  resume checks must call `AgentGoalLifecycleApplicationService` through the
  agent service boundary instead of reading `ApplicationStore.agent_goals`
  directly.
  `ApplicationStore.handle_message`,
  `ApplicationStore._pending_confirmation_invocation`,
  `ApplicationStore._handle_confirmation_message_if_any`, and
  `ApplicationStore._handle_source_binding_message_if_any` are compatibility
  delegates only and must not regain planner, confirmation, source-binding, or
  tool-plan branching logic. During the compatibility phase,
  `ApplicationStore` must hold a constructor-injected
  `conversation_messages` instance and delegate to it directly; it must not
  expose `_conversation_message_app` factories or instantiate this service
  inside message-handling methods.
- `ConversationFallbackApplicationService`: agent-facing fallback response
  boundary used when the planner does not return a direct answer. Conversation
  message use cases must call this service instead of reaching through
  `ApplicationStore` or assembling read-model fallback text inline.
  `ApplicationStore` must not expose `_read_model_summaries`.
- `AgentPlannerContextApplicationService`: planner context assembly boundary.
  It owns deterministic planner memory context packaging, conversation summary
  fallback lookup, and current quality-state delegation. Planner quality state
  must be read through `QualityLoopContextQueryApplicationService`, not direct
  `us_items` or `asset_lanes` reads from the Agent package. `ApplicationStore`
  passes these callables into the planners but must not keep private
  planner-context helper methods.
- `ConversationMessageWriterApplicationService`: canonical conversation
  message write boundary. It owns `ConversationMessage` / `MessageBlock`
  creation, conversation last-message/status projection, repository persistence,
  automatic summary checkpoint triggering, and `conversation.message.created`
  event publication. `ApplicationStore.append_message` is a compatibility
  delegate only.
- `ConversationManagementApplicationService`: conversation lifecycle and
  discovery use cases. It owns scope resolution, create-or-get, listing and
  filtering, search hits, message pagination, archive/unarchive, and merge/link
  creation. Project/version/US scope lookup for conversation creation must be
  delegated to `ProjectScopeResolutionApplicationService`, not direct
  `versions` or `us_items` reads from the Agent package.
  `ApplicationStore` conversation lifecycle methods remain
  compatibility delegates only. During the compatibility phase,
  `ApplicationStore` must hold a constructor-injected
  `conversation_management` instance and delegate to it directly; it must not
  expose `_conversation_management_app` factories or instantiate this service
  inside conversation lifecycle methods.
- `ConversationSummaryCheckpointService`: long-running conversation summary
  checkpoint policy. It owns eligible message filtering, latest checkpoint
  lookup, incremental message range calculation, compact summary text
  construction, and `ConversationSummaryCheckpoint` assembly.
- `ConversationSummaryCheckpointApplicationService`: summary checkpoint write
  boundary. It owns duplicate checkpoint detection, repository persistence,
  conversation latest-checkpoint projection, and `conversation.summary.updated`
  event publication. Summary checkpoints and session-only knowledge bindings
  are PostgreSQL-only facts: `ApplicationStore` and compatibility adapters must
  not retain copies. Automatic checkpoint writes and
  memory-context reads use the Agent application ports and
  `ConversationRepository` directly.
- Planner context must not serialize every complete ToolDefinition on each
  model call. `application/agent/tool_context.py` preserves every registered
  `tool_id` for selection and policy validation, while limiting detailed
  contracts to the tools most relevant to the conversation space and recent
  intent. This packaging is a context optimization only; it does not filter the
  canonical Tool Registry or weaken runtime authorization and governance.
- `application/agent/orchestrator.py`: deterministic Conversation Orchestrator
  for mapping natural language and current space context into the four allowed
  Orchestrator decisions: clarification, direct answer, ToolInvocationPlan, or
  AgentGoalProposal. App-root `conversation_orchestrator.py` is only a
  compatibility re-export; planners, message services, and store compatibility
  delegates must import from the agent application package.
- `AgentReplyApplicationService`: agent LLM reply generation and assistant
  message persistence. Cross-domain query services may depend on this
  application boundary, but they must not call `ApplicationStore` private LLM
  helpers or append conversation messages directly. Its constructor accepts
  only `AgentReplyMemoryPort`, `AgentReplyGenerationPort`,
  `AgentReplyModelSettingsPort`, and `AgentReplyMessageWriterPort`; the service
  must not retain or inspect `ApplicationStore`. The composition root maps
  Agent memory, the LLM gateway, `ModelConfigurationApplicationService`, and
  the canonical conversation message writer to these contracts. Chat provider
  secrets and active model selections therefore remain behind the model
  configuration boundary rather than private Store facades.
- `domain/agent/runtime_models.py`: pure Agent planning value objects for
  `AgentGoalProposal`, `ToolPlanStep`, `ToolInvocationPlan`, and
  `OrchestratorDecision`. These models describe Agent intent and executable
  plan structure without depending on Pydantic, ORM records, LLM clients, or
  workflow adapters.
- `domain/agent/state_machine.py`: pure AgentGoal lifecycle policy for
  checkpoints, phase derivation, start/resume, gate pause, budget pause,
  follow-up pause, failure, and completion. Runtime adapters and application
  services may call it, but it must not import Pydantic DTOs, ORM records, or
  workflow adapters.
- `domain/agent/memory.py`: pure Agent memory context value object plus stable
  context hash and summary functions. It must not import the store, API DTOs,
  retrieval adapters, LLM clients, or workflow adapters.
- `domain/agent/name_extraction.py`: pure Agent project/version name extraction
  policy for English and Chinese user text. Compatibility code may pass
  fallback counters into it, but `ApplicationStore` must not own
  language-specific regexes or fallback naming policy inline.
- `application/agent/memory.py`: application use case for Agent memory. It owns
  the LLM memory package, API-facing memory context view, explicit memory
  checkpoint creation, project long-term memory view, candidate memory view,
  reusable `AgentMemoryItem` / `AgentMemoryLink` persistence, system-image
  memory retrieval tracing, and tool catalog metadata packaging. It may depend
  on the temporary store facade and retriever ports during migration, but
  domain memory value objects stay pure. Conversation summary checkpoint
  selection and construction must use `ConversationSummaryCheckpointService`,
  and automatic checkpoint writes must use
  `ConversationSummaryCheckpointApplicationService`, not `ApplicationStore`
  private helper methods. `ApplicationStore` memory methods are compatibility
  delegates only and must not regain context packaging, checkpoint emission, or
  memory link creation logic. Agent memory context views must obtain AgentGoal
  state through `AgentGoalLifecycleApplicationService`, not direct
  `ApplicationStore.agent_goals` reads. Memory checkpoint events must go through
  `PlatformEventApplicationService`, not
  `ApplicationStore._push_event`.
- `application/agent/plans.py`: application use case for compiling AgentGoal
  proposals into canonical `ToolPlanStep` sequences and for producing
  state-aware follow-up plans after source-binding gates resume.
- `application/agent/planner.py`: application planner for deterministic routing
  and LLM structured planning over the same tool contract surface. It also
  implements the live `AgentReplanner` port, but every replacement plan must
  still pass the domain `AgentPlanPolicy`.
- `application/agent/replanning.py`: application port and DTOs for
  observation-driven replanning. It defines only `keep`,
  `replace_remaining`, and `complete`; graph runtimes consume this port and
  must not call an LLM adapter directly. Provider failure, invalid output, or a
  policy violation retains the already validated pending plan.
- `application/agent/loop.py`: application runtime use case for starting and
  resuming AgentGoals, binding conversation scope, recording audit facts,
  emitting conversation events, and delegating execution to the graph runtime.
  Runtime-level conversation events must go through
  `PlatformEventApplicationService`, not `ApplicationStore._push_event`.
- `application/agent/graph.py`: application graph runtime boundary for
  Think/Act/Observe/Decide execution. It defines the graph protocol,
  Local/LangGraph wrappers, memory-bound step execution, and canonical tool
  invocation sequencing without reading deployment environment variables or
  constructing concrete LangGraph gateway adapters. Agent step events
  (`agent.step.updated`, `agent.step.thinking.delta`, observation, decision,
  and goal updates) must go
  through `PlatformEventApplicationService`, not store private event methods.
  Each observation-driven plan decision must append an
  `agent.goal.replanned` audit fact, including planner kind, confidence,
  removed tools, and added tools.
- `infrastructure/agent/graph_state_dependencies.py`: explicit anti-corruption
  dependencies for graph state. `AgentGraphLookupAdapters` owns Goal and
  Conversation reads, `AgentGraphToolRuntimeAdapters` owns ToolInvocation and
  catalog access, and `AgentGraphMemoryAdapters` owns checkpoint/item/context
  operations. `LegacyAgentGraphStateAdapter` composes these with
  `AgentGoalLifecycleAdapters`; it must not retain `ApplicationStore` or use
  dynamic Store lookup.
- `application/agent/workflow.py`: application port and wrapper types for
  Agent workflow runtimes. It defines Local and Temporal runtime facades without
  reading environment variables or importing Temporal SDK clients.
- `infrastructure/agent/workflow_state_dependencies.py`: explicit workflow
  anti-corruption dependencies. `LegacyAgentWorkflowStateAdapter` receives
  `AgentWorkflowRuntimeAdapters` with goal lookup and remote-goal acceptance
  callbacks; it must not retain `ApplicationStore`, use dynamic Store lookup,
  or mutate the `agent_goals` projection itself.
- `application/platform/distributed_state_sync.py`: temporary cross-process
  projection bridge for Temporal workers. It receives
  `DistributedStateSynchronizationDependencies` containing the mutation
  guard, project/runtime refresh callbacks, and shared projection mappings.
  It must not import or retain `ApplicationStore`; PostgreSQL remains
  authoritative, and an unknown conversation must reject the returned goal
  without leaving an orphan projection.
- `infrastructure/agent/memory_state_dependencies.py`: explicit memory
  anti-corruption dependencies. Durable memory projections and repository
  callbacks are separate from Goal/tool runtime queries, SSE effects,
  candidate knowledge queries, and project-quality snapshot queries.
  `LegacyAgentMemoryStateAdapter` must compose these dependencies without
  retaining `ApplicationStore`; compatibility snapshot mapping remains in
  dedicated infrastructure query objects rather than the application memory
  service.
- `infrastructure/workflow/agent_graph_factory.py`: infrastructure factory
  that reads `NASUS_AGENT_GRAPH_RUNTIME`, constructs the correct graph runtime,
  and wires the LangGraph gateway. Application code must depend on the
  `AgentGraphRuntime` protocol, not on this factory's environment policy.
- `infrastructure/workflow/agent_workflow_factory.py`: infrastructure factory
  that reads `NASUS_AGENT_WORKFLOW_RUNTIME`, constructs the correct runtime, and
  wires Temporal gateway sinks. Sinks that receive returned AgentGoal facts
  must call `AgentGoalProjectionApplicationService` rather than writing
  `ConversationSession.agent_goals` or calling store private projection helpers.
  Durable workflow start and resume payloads must include the authenticated
  actor snapshot. The worker activity restores this request-independent actor
  scope before entering the Agent loop and `ToolInvocationRuntime`, so project
  membership, RBAC, audit identity, and governance decisions remain bound to
  the initiating user rather than a process-default account.
- `application/agent/swarm.py`: application use case for system-image
  materialization swarms, including bounded worker assignments, candidate merge
  summaries, and persistence coordination. Swarm event publication must go
  through `PlatformEventApplicationService`, not `ApplicationStore._push_event`.
- `infrastructure/agent/swarm_state_dependencies.py`: explicit swarm
  anti-corruption state, persistence, and event dependencies.
  `LegacyAgentSwarmStateAdapter` updates the compatibility projection and
  durable repository through separate ports and publishes the canonical SSE
  envelope without retaining `ApplicationStore`.
- `SystemImageApplicationService`: system image source registration, ingestion,
  context materialization, baseline initialization, project knowledge object
  listing, knowledge object detail, and system image snapshot reads.
  `SystemImageToolHandler` must stay a thin adapter: mutations stay in this
  service, status updates go through `ToolInvocationApplicationService`,
  assistant progress messages go through `AgentReplyApplicationService`, and
  materialization swarm startup goes through `AgentApplicationService`.
  `ApplicationStore.list_knowledge_objects`, `ApplicationStore.get_knowledge_object`,
  and `ApplicationStore.get_system_image` remain compatibility delegates only.
  During the compatibility phase, `ApplicationStore` must hold a
  constructor-injected `system_image_app` instance and delegate to it directly;
  it must not expose `_system_image_app` factories or instantiate this service
  inside read methods.
- `application/system_image/service.py`: port-backed system-image lifecycle
  coordinator for source registration, ingestion, raw-asset chunk materialization,
  context materialization, baseline state, quality context, and persistence
  coordination. It depends on `SystemImageWorkspacePort` rather than
  `ApplicationStore`; pure system-image rules must stay in
  `domain/system_image`. The app-root `system_image_service.py` module is a
  compatibility re-export only. The infrastructure anti-corruption adapter
  receives `SystemImageProjectionState` and `SystemImageWorkspaceAdapters`
  from the composition root. It must not retain the Store facade or discover
  repositories, object storage, model settings, provider secrets, access
  policy, or read-model services through Store attributes.
  Startup persistence hydration updates these shared projection mappings in
  place so the workspace, project read models, and compatibility facade always
  observe the same objects.
- `application/system_image/system_image_models.py`: system-image operational
  API contract DTOs, including raw assets/chunks, knowledge objects, baselines,
  context relationships/overlays, quality metric snapshots, embedding/
  retrieval/rerank records, task contexts, quality profiles, build state, and
  system image snapshots. Root `models.py` may re-export these names only as a
  migration compatibility facade; new code must import them from
  `application.system_image.system_image_models`.
- `application/platform/project_models.py`: project and version read-model
  contracts (`ProjectCard`, `VersionSummary`) shared by portfolio, workspace,
  persistence, and system-image snapshots. Root `models.py` may re-export these
  names only during migration; new code must import them from
  `application.platform.project_models`.
- `infrastructure/system_image/source_ingestion.py`: infrastructure adapter for
  source ingestion. It owns local filesystem reads, allowed source URI schemes,
  file/byte limits, raw-source fingerprints, and raw text-unit extraction.
  System-image application services may depend on this adapter during the
  migration, but app-root `source_ingestion.py` is only a compatibility
  re-export and must not regain implementation.
- `infrastructure/system_image/ingestion_projection.py`: write-side compatibility
  projection for source ingestion. It receives the shared mutation-guard
  factory, `SystemImageWorkspacePort`, and read-model refresh boundary through
  composition; it must not retain `ApplicationStore`.
- `application/system_image/context_extraction.py`: application-level context
  extraction service for turning indexed code, US documents, and test assets
  into system-image knowledge objects, relationships, and quality metric
  snapshots. It stays in the system-image application package because it maps
  raw source facts into current API/store DTOs; app-root
  `context_extraction.py` is only a compatibility re-export.
- `application/system_image/knowledge_queries.py`: system-image knowledge
  object query service. It owns project read-model refresh before knowledge
  reads and the temporary store-backed `knowledge_objects` lookup.
  `SystemImageApplicationService` must delegate list/detail knowledge reads to
  this service instead of reading store collections inline.
- `application/system_image/snapshots.py`: system-image snapshot query service.
  It owns the temporary store-backed `system_image_service.get` delegation.
  `SystemImageApplicationService` must delegate snapshot reads here rather than
  mixing read aggregation into the facade.
- `application/system_image/lifecycle.py`: context materialization and Official
  System Image baseline lifecycle use cases. It owns materialization and
  baseline initialization delegation while `SystemImageService` remains
  store-backed.
- `application/system_image/source_bindings.py`: system-image source binding
  and ingestion entry-point service. It owns project existence checks, source
  spec normalization, missing-source checks, source registration, and ingestion
  delegation while the deeper `SystemImageService` remains store-backed.
  `SystemImageApplicationService` must delegate these source use cases here
  instead of calling `system_image_service` inline.
- `application/system_image/raw_asset_chunks.py`: raw asset chunk
  materialization application component. It owns converting indexed source text
  units into `RawAssetChunk` records, storing chunk payloads, and reading chunk
  text back for embedding/context assembly. `SystemImageService` should call
  this component instead of owning chunk loops inline.
- `application/system_image/source_ingestion.py`: source registration and
  ingestion write-side application component. It owns clearing derived context
  when sources are rebound, creating/updating `RawAssetRecord` bindings,
  applying ingestion status transitions, mapping permission/OS failures,
  invoking the infrastructure source ingestion adapter, triggering raw-asset
  chunk materialization for indexed sources, and persisting/refetching read
  models. `SystemImageService.register_sources` and
  `SystemImageService.ingest_sources` are compatibility entry points and should
  delegate to this component instead of restoring source write loops inline.
- `application/system_image/embedding_records.py`: embedding record
  materialization application component. It owns constructing embedding inputs
  for chunks, sources, and knowledge objects, resolving the active embedding
  model API key through `ModelConfigurationApplicationService`, calling the
  embedding provider, assigning vector refs, and writing chunk embedding ids.
  `SystemImageService` should coordinate this component instead of owning
  embedding provider orchestration inline.
- `application/system_image/quality_contexts.py`: quality-context materialization
  application component. It owns task-context target selection, retrieval run
  construction, rerank provider calls, `TaskContext` generation, and
  `QualityProfile` scoring using `domain/system_image/quality_context.py`
  policies. `SystemImageService` should only trigger this component during
  lifecycle materialization and must not regain inline rerank or quality-profile
  loops.
- `application/system_image/seed_contexts.py`: seed/fallback context fact
  application component. It owns deterministic bootstrap `KnowledgeObject`,
  `ContextRelationship`, `ContextObjectOverlay`, and `QualityMetricSnapshot`
  creation, fallback context materialization, and draft-context cleanup.
  `SystemImageService` may ask this component to seed or clear lifecycle facts,
  but must not construct these fact records inline.
- `application/system_image/persistence.py`: system-image read-model
  persistence boundary. It is the only application component that may call
  `project_repository.replace_system_image`. System-image lifecycle, Agent
  memory retrieval tracing, Governance baseline promotion, and quality-loop
  image updates must call `SystemImagePersistenceApplicationService.persist`
  instead of private service helpers or repositories directly.
- `application/system_image/us_work_items.py`: US work item synchronization
  application component. It owns deriving `USItem` facts from system-image
  context through `domain/system_image/us_work_items.py`, creating default
  quality asset lanes, and persisting US/asset-lane read models.
  `SystemImageService` should call this component after context materialization
  instead of constructing US work items or lanes inline.
- `application/system_image/retrieval.py`: Agent-facing system-image retrieval
  port plus the default in-process retriever over current read models. Agent
  memory may depend on this boundary; it must not import the app-root
  `system_image_retriever.py` compatibility module. Future vector/code-graph
  retrievers should implement this port instead of changing Agent memory. The
  infrastructure implementation receives `SystemImageRetrievalState` and the
  raw-chunk text reader explicitly; it must not retain Store or locate
  `SystemImageService` through Store attributes.
- `domain/system_image/source_binding.py`: pure source-binding policy for
  required source types, placeholder source URIs, missing source detection, and
  ingestion readiness. `SystemImageService` may gather current project state,
  but required-source branching must live in this domain policy.
- `domain/system_image/build_state.py`: pure Official System Image build-state
  policy for failure precedence, missing source requirements, ingesting/indexed
  progression, materialized-but-not-promoted status, and ready status.
  `SystemImageService` may pass current source statuses, baseline status,
  context flags, and project status, but transition labels and recommended
  tools must live in this domain policy.
- `domain/system_image/chunking.py`: pure raw-asset chunking policy for text
  normalization, chunk splitting, content hashes, deterministic chunk IDs,
  source-type-to-chunk-kind mapping, token estimation, and stable hashes.
  `SystemImageService` may coordinate ingestion, object storage, and
  persistence, but chunk identity and classification rules must live in this
  domain policy. Embedding/rerank provider secrets and active model selections
  must be supplied through the model settings/key provider ports assembled by
  the composition root; system-image code must not construct
  `ModelConfigurationApplicationService` or call private `ApplicationStore`
  model-configuration facades directly.
  Production-like profiles enforce a fail-closed model-route policy:
  embedding and rerank results must report `mode=live`. Provider timeouts,
  unsupported providers, mock hash vectors, and rule-based rerank fallbacks
  fail materialization instead of creating formal context facts. Local and
  development profiles may retain explicit fallback records for diagnostics.
- `application/system_image/materialization_snapshot.py`: application
  transaction boundary for context materialization. Indexed source records may
  remain durable after a failed attempt, but context objects, relationships,
  metrics, generated US work items, embedding/index rows, rerank records, task
  contexts, quality profiles, project progress, and baselines must return to
  the pre-materialization snapshot.
- `domain/system_image/quality_context.py`: pure quality-context policy for
  missing quality context detection, deterministic context hashes, confidence,
  risk, coverage, automation feasibility, release scoring, and risk-driver
  explanations. `SystemImageService` may gather sources, metrics,
  relationships, and project counters, but these scoring formulas must live in
  this domain policy.
- `domain/system_image/us_work_items.py`: pure policy for deriving US work
  items from system-image knowledge objects and assigning default quality asset
  lanes. `SystemImageUSWorkItemApplicationService` may map decisions into
  current API DTOs and persist them, but service coordinators must not own
  US-object selection, US code extraction, default US attributes, or lane
  templates inline.
- `application/quality_loop/project_versions.py`:
  `ProjectVersionApplicationService` owns project setup, version creation,
  project asset connection, version input import, branch binding, participant
  assignment, version risk initialization, and US task-start write use cases.
  `ProjectVersionToolHandler` must remain a thin adapter: mutations stay in
  this service, status updates go through `ToolInvocationApplicationService`,
  and assistant progress messages go through `AgentReplyApplicationService`.
  The service depends on `ProjectVersionWorkspacePort`,
  `QualityLoopContextReadPort`, and `SystemImageOperationsPort`; it must not
  read compatibility dictionaries or repositories. Production composition
  binds the workspace port to
  `infrastructure/quality_loop/SQLAlchemyProjectVersionWorkspace`, which uses
  durable PostgreSQL facts and entity-grained project/version/US writes.
  `LegacyProjectVersionWorkspace` is test/migration-only.
  Project and version record creation defaults and release-readiness seed
  records are part of this application service contract, while persistence,
  project-access grants, conversation creation, and system-image draft
  initialization are effects behind the workspace port.
  `ApplicationStore.create_project` and
  `ApplicationStore.create_version` remain compatibility delegates only
  during migration. Do not add
  project/version setup logic back to
  `application/quality_loop/use_cases.py`; that file is reserved for
  `QualityLoopApplicationService` orchestration.
- `QualityLoopApplicationService`: compatibility facade for quality-loop write
  use cases. It may expose legacy tool-handler entry methods, but it must
  delegate quality-step completion to `QualityStepCompletionApplicationService`,
  automation runner execution to `QualityRunExecutionApplicationService`, and
  concrete fact mutations to the owning application services below. The
  composition root injects every collaborator explicitly; this service must not
  retain `ApplicationStore`, discover dependencies through Store attributes,
  or instantiate subordinate application services.
- `QualityStepCompletionApplicationService`: write boundary for scope/scenario/
  case, automation, and release quality-step completion. It consumes pure plans
  from `domain/quality_loop/quality_step_plan.py`, invokes runner-backed
  automation through `QualityRunExecutionApplicationService`, creates failure
  reports when automation fails, records metric overlays through
  `QualityImageUpdateApplicationService`, writes asset parts through
  `QualityAssetPackApplicationService`, and persists lane/US progress through
  `QualityAssetProgressApplicationService`. Do not add quality-step plan
  execution logic back to `application/quality_loop/use_cases.py`. Prior asset
  context is read through `QualityAssetPackApplicationService`, not Store
  projections.
- `QualityRunExecutionApplicationService`: run execution boundary for
  quality-loop automation. It consumes `QualityAutomationExecutionPort`,
  `QualityAssetPackReadPort`, and `QualityExecutionEvidenceReadPort`, validates
  the approved automation blueprint before dispatch, maps returned execution
  evidence into canonical `execution_evidence` refs, and exposes durable
  evidence lookup for release planning. PostgreSQL-backed reads and runner
  lifecycle effects remain infrastructure concerns; the application service
  must not depend on `ApplicationStore` or compatibility projections.
- `QualityLoopVersionContextApplicationService`: active-version boundary for
  quality-loop writes. It owns active version resolution and creation of the
  default `Initial Quality Loop` version when quality-loop facts need a version
  context. The canonical creation operation is delegated to
  `ProjectVersionApplicationService.active_or_create_quality_version`, so
  `us.task.start` and downstream quality-step services use the same resolution
  semantics. If system-image materialization produced unversioned US facts
  before a business Version existed, this operation moves them exactly once
  into the first Version. It must never move or copy US records between later
  Versions. Pass this provider to asset-pack, release-readiness, and
  quality-image update services instead of letting the main quality-loop use
  case read `versions` or create default versions inline.
- `ProjectVersionWorkspacePort.list_us_items`, `save_us_items`, and
  `save_us_item` are version-scoped persistence contracts. Production adapters
  query by `(project_id, version_id)` and upsert only the supplied US rows;
  omitted peer rows must never be deleted. `version_id=None` is restricted to
  the one-time pre-Version system-image compatibility set. Moving those rows
  into the first Version is an ownership update, not a copy-and-clear bulk
  replacement. Project workspace read models expose only the active Version's
  US collection by default.
- `QualityAssetPackApplicationService`: write-side boundary for
  `QualityAssetPack` facts. It owns pack initialization/refresh,
  `QualityAssetPart` upsert, revisioning, pack status/current revision/evidence
  aggregation, source-reference resolution, and persistence through
  `QualityAssetPackWorkspacePort`. Production persistence is implemented by
  `infrastructure/quality_loop/SQLAlchemyQualityAssetPackWorkspace` against
  PostgreSQL. `LegacyQualityAssetPackWorkspace` is test/migration-only.
  `QualityStepCompletionApplicationService` should consume quality-step plans
  and delegate pack writes here.
- `QualityAssetProgressApplicationService`: quality asset lane and US board
  progress write boundary. It owns default lane materialization, lane
  status/summary persistence, and US progress/status/next-action persistence
  through `QualityAssetProgressWorkspacePort`.
  `QualityStepCompletionApplicationService` consumes quality-step plans and
  delegates these updates instead of directly editing `asset_lanes` or
  `us_items`; production composition uses
  `infrastructure/quality_loop/SQLAlchemyQualityAssetProgressWorkspace` for
  target-lane and target-US writes. `LegacyQualityAssetProgressWorkspace` is
  test/migration-only.
- `QualityFailureReportApplicationService`: failure-analysis write boundary.
  It reads evidence through `QualityExecutionEvidenceReadPort`, materializes
  missing evidence through `QualityAutomationExecutionPort`, delegates failure
  fingerprinting and report decisions to the domain policy, and writes the
  updated `Run` plus affected `FailureReport` facts through
  `QualityFailureWorkspacePort`. `SQLAlchemyQualityFailureWorkspace` must
  persist the target run and reports in one PostgreSQL transaction without
  deleting peer facts created by concurrent workers. This application service
  must not depend on `ApplicationStore`
  or repositories directly. The main quality-loop use case should only decide
  when failure analysis/healing is needed and delegate the fact mutation here.
- `QualityReleaseReadinessApplicationService`: release-readiness write
  boundary. It gathers open FailureReports, delegates readiness scoring to the
  domain policy, persists `ReleaseReadiness`, and synchronizes project
  progress/blocker/risk fields. The main quality-loop use case should only ask
  for release advice or assessment and delegate release-readiness mutations
  here.
- `QualityImageUpdateApplicationService`: cross-context write boundary for
  quality-loop metrics materialized into the system image. It creates
  `QualityMetricSnapshot` and `ContextObjectOverlay` records, keeps baseline
  metric counters current, ensures a baseline exists, and persists the
  system-image read model through `QualityImageWorkspacePort`. The main
  quality-loop use case should only pass quality-step metric specs to this
  service. It must not retain `ApplicationStore`, mutate compatibility
  dictionaries, or call repositories directly.
- `QualityLoopContextQueryApplicationService`: current quality-loop context
  query boundary for write-side use cases. It resolves the current
  `TaskContext`, `QualityProfile`, `QualityAssetPack`, and planner-facing
  quality state through `QualityLoopContextWorkspacePort`. Agent,
  project/version, and quality-loop application services must depend on this
  service instead of reading compatibility caches, calling repositories, or
  reintroducing `ApplicationStore._current_*` private helpers or platform BFF
  read models. Production context reads are implemented by
  `infrastructure/quality_loop/SQLAlchemyQualityLoopContextWorkspace` against
  durable repositories. `LegacyQualityLoopContextWorkspace` is
  test/migration-only.
- `QualityLoopScopeQueryApplicationService`: ToolInvocation scope query
  boundary for quality-loop actions. It resolves project, US, failed-run scope,
  and route query keys from invocation payloads, conversation scope, run
  summaries, execution evidence, and US ownership through
  `QualityLoopScopeWorkspacePort`. Unknown or cross-project project/US/run
  combinations fail closed before write-side execution. Keep these inference
  rules here instead of in write-side use-case methods. Production ownership
  reads belong to
  `infrastructure/quality_loop/SQLAlchemyQualityLoopScopeWorkspace`, which
  resolves conversations, US items, runs, and execution evidence from durable
  repositories instead of process-local projections.
- `QualityLoopReleaseDecisionQueryApplicationService`: release decision query
  boundary for governance use cases. Platform governance may submit approvals
  and promote baselines, but it must read current `ReleaseDecision` facts
  through this quality-loop service and
  `QualityLoopReleaseDecisionReadPort` instead of calling or reintroducing
  `ApplicationStore._current_release_decision`, reading compatibility
  projections, or using platform workspace read models. `QualityLoopRepository`
  implements the production read port against PostgreSQL and returns the
  deterministic latest fact.
- `application/quality_loop/quality_models.py`: quality-loop operational API
  contract DTOs, including US work items, quality asset lanes, asset
  packs/parts, run summaries/details, execution evidence, failure reports,
  approval details, release decisions/readiness, and `QualityLoopState`. Root
  `models.py` may re-export these names only as a migration compatibility
  facade; new code must import them from `application.quality_loop.quality_models`.
- `domain/quality_loop/release_readiness.py`: pure release-readiness decision
  policy for blocked-vs-ready status, release score, blocker count, approval
  count for human fallback, execution health text, release summary, blocker item
  formatting, and project progress floor. Application services may collect open
  failures and persist `ReleaseReadiness`, but scoring/status rules must live in
  this domain policy.
- `domain/quality_loop/release_decision.py`: pure release-decision policy for
  status selection (`ready`, `conditional`, `blocked`, `needs_evidence`),
  stable decision IDs, rationale text, and evidence reference composition.
  Governance application services may collect readiness and execution evidence
  and persist `ReleaseDecision`, but release-decision rules must live in this
  domain policy.
- `domain/quality_loop/quality_assets.py`: pure quality-asset policy for
  default asset-lane templates, legacy/canonical lane matching, quality asset
  part revision increments, QualityAssetPack status transitions, current
  revision calculation, and evidence aggregation. Application services may map
  decisions into API DTOs and persist them, but they must not own lane template
  or pack status rules inline.
- `domain/quality_loop/quality_step_plan.py`: pure quality-step plan policy
  for scope/scenario/case generation, automation outcome handling, and
  post-readiness release assessment, including lane updates, US
  progress/status/next-action transitions, quality metric specs,
  QualityAssetPart specs, object/evidence refs, summary text, failure-report
  requirements, and next-tool sequencing. Application services may execute
  these plans by calling persistence helpers and may invoke runners, create
  `FailureReport`, and collect release evidence refs, but quality-step rule
  tables must not live inline in application services.
- `domain/quality_loop/failure_analysis.py`: pure failure-analysis and bounded
  healing policy for stable failure identity/fingerprint generation,
  failure-kind classification, healing attempt counts, fallback-to-human
  decisions, run healing status, and root-cause text. Application services may
  collect evidence, find prior reports, create DTOs, and persist run/report
  updates, but failure decision rules must live in this domain policy.
- `domain/quality_loop/failure_loop_progress.py`: pure failed-run loop progress
  policy for analysis/healing/fallback summary text, next-tool selection,
  assistant progress copy, planner kind, and fallback-to-human flags.
  Application services may resolve failed-run scope, persist `FailureReport`,
  and attach run/report object refs, but failure-loop progress branching and
  copy must live in this domain policy.
- `domain/quality_loop/step_guidance.py`: pure quality-loop step guidance
  policy for runtime progress summaries, assistant follow-up copy, and fallback
  guidance. Application services and tool handlers may request guidance for a
  step, but step-to-copy maps must live in this domain policy.
- `domain/quality_loop/version_participants.py`: pure version participant
  assignment policy for assignment-payload normalization, explicit/default/
  existing owner precedence, Unassigned fallback, and assigned-count decisions.
  Project/version application services may map decisions into `USItem` updates
  and persist them, but assignment shape parsing and owner fallback rules must
  live in this domain policy.
- `domain/quality_loop/version_risk.py`: pure version-risk initialization
  policy for US risk bucketing, default next-action fallback, aggregate project
  risk, project progress floor, and initialization summary text. Project/version
  application services may collect current US items and persist updated
  project/version facts, but thresholds and summary rules must live in this
  domain policy.
- `domain/quality_loop/version_us_import.py`: pure version US input-import
  policy for supported payload keys, raw item normalization, generated-ID
  injection, default US attributes, merge rules, progress monotonicity, imported
  item decisions, and ordered US board decisions. Project/version application
  services may supply an ID factory, map decisions into API DTOs, and persist
  them, but raw payload parsing and import merge rules must live in this domain
  policy.
- `domain/quality_loop/us_task_start.py`: pure US task-start policy for
  requested-or-first target selection, analysis status transition, progress
  floor, next-action copy, assistant summary text, context-sensitive next tools,
  and follow-up decisions. Project/version application services may persist
  updated US items, materialize system-image context, and attach object refs,
  but task-start rules and response copy must live in this domain policy.
- `GovernanceApplicationService`: approval request/decision, structured merge
  resolution, release decision submission, and baseline promotion write use
  cases. Tool handlers may emit runtime status, but governance state mutations
  belong in this service and later in `domain/platform` and
  `domain/quality_loop` policies.
- `QueryToolApplicationService`: tool-native read-model query planning,
  fallback summary selection, LLM answer generation, assistant message
  persistence, and read ToolResult construction. Tool handlers may emit runtime
  status, but cross-domain query summary assembly belongs in this service and
  later in bounded query/read-model services. It reads through
  `AgentQueryReadPort`; the current compatibility projection is translated by
  `infrastructure/platform/CompatibilityPlatformQueryReadModel`.
- `AccountApplicationService`: current user reads, registration, login/logout,
  avatar upload or preset selection, avatar content reads, authenticated-user
  binding for the compatibility facade, and auth-service error mapping. It
  receives `CurrentUserProviderPort` and `AccountIdentityPort`; the service must
  not retain `ApplicationStore` or construct a concrete identity provider. The
  bootstrap container injects a request-local actor adapter and the current
  PostgreSQL/MinIO identity implementation.
  `PlatformApplicationService` delegates account operations to this service and
  must not regain direct `AuthService`, avatar branching logic, or direct
  `ApplicationStore` state mutation.
- `application/platform/account_models.py`: application-layer account contract
  for user profile, register/login payloads, session response, and avatar
  update payloads. App-root `models.py` may re-export these types during
  migration, but HTTP auth, platform routes, account services, and store
  compatibility code must import them from
  `application.platform.account_models`.
- `application/platform/read_models.py`: platform read-model response
  contracts for documentation, build, dashboard, welcome, and project
  workspace views, plus cross-domain summary helpers for agent-facing query
  tools. App-root `models.py` may re-export these response DTOs during
  migration, but `ApplicationStore`, routes, and new query/read-model code must
  import them from `application.platform.read_models`.
- `TopLevelContentApplicationService`: platform-owned BFF read assembly for
  Welcome, Build, Dashboard, and Documentation. `PlatformApplicationService`
  delegates these page reads to this service; `ApplicationStore` keeps only
  compatibility delegate methods and must not directly assemble
  `WelcomeResponse`, `BuildResponse`, or `DashboardResponse`. During the
  compatibility phase, `ApplicationStore` must hold a constructor-injected
  `top_level_content` instance backed by `TopLevelContentReadPort` and delegate
  to it directly. Top-level application code must not read Store maps.
- `DemoSeedApplicationService`: local/demo seed-data application component.
  It owns the Payment System seed project, version, US items, quality-loop
  lanes, run/approval examples, documentation examples, release-readiness
  example, system-image readiness seeding, and initial demo conversations.
  `ApplicationStore._seed` is a compatibility delegate only and must not
  contain demo object construction or repository write loops inline. During the
  application service depends only on `DemoSeedWorkspacePort`.
  `SQLAlchemyDemoSeedWorkspace` is the local-only production adapter and writes
  idempotent seed facts through project, quality-loop, system-image, and
  conversation repositories. `CompatibilityDemoSeedWorkspace` is retained for
  migration tests only. Neither component receives `ApplicationStore`.
  The compatibility facade delegates to the constructor-injected service and
  must not instantiate it inside `_seed`.
- `application/platform/auth_service.py`: stable authentication result and
  error contracts. `SQLAlchemyAccountIdentityService` under
  `infrastructure/platform` owns PostgreSQL identity/session persistence,
  password hashing, and MinIO avatar object storage, and implements
  `AccountIdentityPort`. Application account use cases do not import ORM or
  storage implementations. App-root `auth_service.py` is only a compatibility
  re-export. HTTP auth
  middleware must call `PlatformApplicationService.authenticate_token` through
  a token authenticator callback and then
  `PlatformApplicationService.bind_authenticated_user` instead of constructing
  identity infrastructure directly or assigning `store.user`.
- `ModelConfigurationApplicationService`: settings reads and updates, provider
  connection tests, multi-instance model configuration, test-token validation,
  payload fingerprinting, active route selection, and legacy model import.
  It consumes `ModelConfigurationStatePort`, repository, secret, provider
  gateway, and durable test-grant ports. PostgreSQL, API-key encryption and LLM
  adapters are injected by the composition root; the application service must
  not retain `ApplicationStore`. Store model-setting methods are compatibility
  delegates and must not own provider/model selection rules.
- `application/platform/model_settings.py`: application-layer contract for
  studio settings, provider status, and saved chat/embedding/rerank model
  configurations. App-root `models.py` may re-export these types during
  migration, but new platform services, persistence adapters, LLM adapters, and
  HTTP routes must import the contract from `application.platform.model_settings`
  instead of adding model-configuration DTOs back to the global model bucket.
- `ToolInvocationApplicationService`: tool catalog reads, ToolInvocation
  create/confirm/execute/gate application entry points, invocation filtering,
  runtime status emission, invocation update SSE emission, and audit-event query
  use cases. It is constructor-injected with
  `ToolInvocationApplicationStatePort`, `ToolInvocationExecutionPort`,
  `ToolInvocationAccessPort`, and `ToolStatusEventPort`; neither the service nor
  `infrastructure/platform/tool_invocation_state.py` may retain
  `ApplicationStore`. Tool handlers and `ToolInvocationRuntime` emit status and
  update events through `ToolStatusEventPort`, implemented by
  `PlatformEventApplicationService`, instead of depending on this concrete
  service or Store private event methods. During migration,
  `ApplicationStore` may hold the composed `tool_invocations_app` delegate but
  must not expose `_tool_invocation_app` factory helpers.
- `SQLAlchemyToolInvocationRuntimeState`: production command-state adapter for
  ToolInvocation creation, confirmation, execution claims and restart recovery.
  It reads committed PostgreSQL facts, creates requests behind the
  `uq_tool_invocation_idempotency` constraint and acquires a row lock before
  changing an eligible invocation to `running`. Reusing one idempotency key for
  a different canonical payload returns `409 tool_idempotency_conflict`.
  `ProjectedToolInvocationRuntimeState` remains test/migration-only, and the
  compatibility projection may mirror committed updates but cannot decide
  whether an invocation is new, confirmable or executable.
- `ToolInvocationProjectionApplicationService`: ToolInvocation fact persistence
  for conversation read models. It depends only on
  `ToolInvocationProjectionStatePort`. The production adapter is
  `infrastructure/platform/SQLAlchemyToolInvocationProjectionState`; it writes
  the ToolInvocation row once, while `ConversationRepository` assembles
  `ConversationSession.tool_invocations` by `conversation_id` on every read.
  Production therefore has no process-local ToolInvocation mirror and does not
  rewrite Conversation after status changes. The projected adapter is retained
  only for isolated compatibility tests; neither adapter nor the application
  service retains `ApplicationStore`. Runtime, event publication,
  and store compatibility methods must call this service instead of duplicating
  projection logic or calling `ApplicationStore._upsert_invocation_in_conversation`
  directly. `ApplicationStore._upsert_invocation_in_conversation` is a
  compatibility delegate only. During the compatibility phase,
  `ApplicationStore` must hold a constructor-injected `tool_projection`
  instance and delegate to it directly; it must not instantiate this service
  inside projection methods.
- `PlatformAuditApplicationService`: platform audit write use cases. It owns
  generic audit persistence and AgentGoal audit-event payload construction. It
  depends only on `AuditEventPersistencePort`; the production
  `SQLAlchemyAuditEventPersistence` adapter writes append-only events directly
  to PostgreSQL. `ProjectedAuditEventPersistence` is test/migration-only and
  cannot supply production query facts. Neither layer may retain
  `ApplicationStore`.
  `ApplicationStore.record_audit_event` and
  `ApplicationStore.record_agent_goal_audit_event` are compatibility delegates
  only and must not construct `AuditEvent` payloads inline. During migration,
  `ApplicationStore` may hold an injected `platform_audit` instance, but it must
  not expose `_audit_app` factory helpers.
- `PlatformEventApplicationService`: platform SSE/outbox event publication use
  cases. It owns `EventPayload` construction, entity-version increments,
  tool-status event emission, and swarm snapshot event construction. Queue
  creation, conversation/goal/swarm fan-out, and stream iteration must go
  through `PlatformEventStreamApplicationService`. ToolInvocation fact
  persistence and conversation projection must go through
  `ToolInvocationEventProjectionPort`. AgentGoal, ToolInvocation, and AgentSwarm
  snapshot payload reads must go through `PlatformEventEntityReaderPort`.
  Production ToolInvocation event payload reads use
  `SQLAlchemyToolInvocationApplicationState`; an API-local invocation mapping
  is never the event source of truth.
  `PlatformEventApplicationService` must not retain `ApplicationStore`, inspect
  compatibility dictionaries, or construct concrete event/projection services.
  `ApplicationStore` must not expose `_push_event`, `_push_goal_event`,
  `_event_payload`, `_emit_tool_status`, or `_emit_simple_answer`. Temporary
  stream compatibility methods may remain only while routers still consume the
  store facade. During migration, `ApplicationStore` may hold an injected
  `platform_events` instance, but it must not expose `_event_app` factory
  helpers.
- `PlatformEventStreamApplicationService`: durable SSE stream boundary. Every
  event is appended through `EventOutboxPort` before fan-out; process-local
  queues are accessed only through `EventStreamBufferPort`. Stream readers replay
  by `Last-Event-ID`, poll the outbox so reconnects and multiple API instances
  observe the same ordered log, and emit heartbeat comments while idle.
  Process-local queues are only low-latency wake-up signals; they are not the
  event system of record. Production composition names this adapter
  `SSEWakeUpBuffer`; `ProjectedEventStreamBuffer` remains a compatibility alias
  only. Poll and heartbeat configuration is resolved in
  `infrastructure/platform/event_runtime.py` and injected into the service.
  The application service must not read environment variables or retain
  `ApplicationStore`. Store queue helpers such as
  `_get_or_create_event_queue`, `_get_or_create_goal_queue`, and
  `_get_or_create_swarm_queue` must not exist or regain persistence policy.
- `application/platform/tool_models.py`: platform tool-command contract types
  for `ToolDefinition`, `ToolInvocation`, `ToolResult`,
  `ToolInvocationRequest`, `AuditEvent`, and `EventPayload`. App-root
  `models.py` may re-export these names during migration, but tool runtime,
  tool handlers, Tool Catalog, persistence adapters, Agent graph/message
  orchestration, and HTTP platform routes must import them from this
  application-layer contract instead of adding tool DTOs back to the global
  model bucket.
- `application/platform/tool_catalog.py`: platform-owned Tool Catalog
  definitions for first-party tools across project/version, quality-loop,
  governance, query, and system-image groups. `ApplicationStore` may assemble
  catalog groups during migration, but must not define `ToolDefinition(...)`
  inline. App-root `system_image_tool_catalog.py` is only a compatibility
  re-export. Future catalog groups may be split into a `tool_catalog/` package,
  but must remain under the platform application boundary.
- `application/platform/runtime.py`: canonical ToolInvocation lifecycle runtime
  for every business tool action. It owns idempotent invocation creation,
  canonical aliases, RBAC invocation, confirmation/approval gate dispatch,
  handler dispatch, and audit persistence. The app-root
  `tool_invocation_runtime.py` module is a compatibility re-export only, while
  `ApplicationStore` tool/audit methods are compatibility delegates.
- `domain/platform/rbac.py`: pure tool RBAC policy for role normalization,
  role aliases, role ordering, required-role thresholds, and authorization
  denial summaries. `ToolInvocationRuntime` may invoke this policy, but must
  not own the role threshold table inline. App-root `rbac.py` is a compatibility
  re-export only.
- `domain/platform/tool_governance.py`: pure tool governance-gate policy for
  confirmation phrase detection, user-confirm gates, approval-required gates,
  approval verifier results, and gate decision summaries.
  `ToolInvocationRuntime` may invoke this policy, but must not own
  waiting-confirmation or waiting-approval branching inline. App-root
  `tool_governance.py` is a compatibility re-export only.
- `ToolApprovalVerifierApplicationService`: application verifier for
  approval-required tool invocations. It resolves project context from
  invocation payload or conversation scope, checks project approval membership,
  and validates approved/accepted/completed status through
  `ToolApprovalVerificationStatePort`. Production composition uses
  `SQLAlchemyToolApprovalVerificationState`, backed by durable conversation and
  approval repositories. `ProjectedToolApprovalVerificationState` is
  test/migration-only; neither the application service nor its port may retain
  `ApplicationStore` or scan Store projections. The
  composition root wires the verifier into `ToolGovernance`.
- `application/platform/tool_handlers/`: platform-owned ToolInvocation adapter
  package. It contains the registration-only `ToolInvocationHandlerRegistry`
  plus thin adapters for system-image, project/version, quality-loop,
  governance, and query tools. These adapters accept domain application
  services plus `ToolStatusEventPort`, never the concrete
  `ToolInvocationApplicationService`; they must not import, type-check, or
  construct `ApplicationStore` directly. App-root
  `*_tool_handlers.py` modules are compatibility re-exports only.
- `ReadModelSummaryService`: cross-domain read-model summary policy for
  dashboard, project, version, workspace, knowledge, system-image, run,
  governance, and conversation fallback text. `ApplicationStore` summary helper
  methods are compatibility delegates and must not grow new summary logic. The
  service depends on `AgentQueryReadPort`; `read_query_ports.py` is the canonical
  application contract for query and top-level projections.
- `PlatformApplicationService`: HTTP-facing platform facade for account,
  settings/model configuration, top-level studio reads, tool catalog, tool
  invocation, and audit query use cases. It must compose dedicated application
  services such as `AccountApplicationService`,
  `ModelConfigurationApplicationService`, `TopLevelContentApplicationService`,
  `ToolInvocationApplicationService`, and `PlatformAuditApplicationService`;
  it must not keep a `self._store` escape hatch, mutate `ApplicationStore`
  directly, or call compatibility-store methods inline.
- `ProjectWorkspaceApplicationService`: project workspace aggregation,
  project/version creation through tool invocation, workspace reads, run reads,
  approval reads, and release readiness reads. It owns project workspace
  read-model assembly, current-US selection, quality-loop state projection, and
  workspace detail payload composition. `ApplicationStore.get_project_workspace`,
  `ApplicationStore.get_workspace_data`, `ApplicationStore.get_run_detail`,
  `ApplicationStore.get_approval_detail`, and
  `ApplicationStore.get_release_readiness` remain compatibility delegates only.
  `ApplicationStore` must not expose private project workspace facades such as
  `_current_task_context`, `_current_quality_profile`,
  `_current_quality_asset_pack`, `_current_release_decision`,
  `_quality_loop_state`, or `_select_project_workspace_us`.
  The service depends only on `ProjectWorkspaceReadPort`,
  `ProjectWorkspaceAuthorizationPort`, `ProjectWorkspaceToolPort`, and
  `ProjectWorkspaceConversationPort`. Cross-domain workspace payloads are read
  through `infrastructure/platform/SQLAlchemyProjectWorkspaceReadModel`, which
  composes project, system-image, and quality-loop repositories without
  hydrating `ApplicationStore`. Commands continue through the canonical Tool
  Invocation application boundary. During the compatibility phase,
  `ApplicationStore` may hold a constructor-injected `project_workspace`
  delegate, but production HTTP composition constructs the service explicitly
  in `bootstrap/container.py`.
  It must not own system-image read concerns once `SystemImageApplicationService`
  exposes them.
- `ProjectReadModelRefreshApplicationService`: platform read-model projection
  boundary for notifying project-facing reads after a commit. Production
  composes `RepositoryBackedProjectReadModelProjection`; refresh is a no-op
  because every project, quality-loop, and system-image query reads PostgreSQL.
  The application service may depend only on `ProjectReadModelProjectionPort`.
  `CompatibilityProjectReadModelProjection` and its mutable state are
  migration-test fixtures and must not be composed by the API runtime.
  `ApplicationStore._refresh_project_read_models` is compatibility-only and
  delegates to the constructor-composed service. Ingestion adapters receive the
  service through constructor injection and must not construct subordinate
  application services. The infrastructure
  adapter reads project/version data through `ProjectRepository`, system-image
  data through `SystemImageRepository`, and quality-loop data through
  `QualityLoopRepository`; it must not use `ProjectRepository` as a
  cross-context persistence gateway.
- `ProjectStateLoaderApplicationService` and `ProjectStateHydrationPort` remain
  migration-test fixtures. Production does not hydrate project facts at
  startup and must not compose either type.
- Agent runtime facts have no startup hydration layer. Conversation, links,
  goals, summaries, session knowledge, memory, swarms, ToolInvocation, and
  AuditEvent are queried through their PostgreSQL repositories on every use
  case. The composition root must not define runtime compatibility maps,
  `RuntimeStateLoaderApplicationService`, `RuntimeStateHydrationPort`, or a
  Conversation projection sink. Distributed AgentGoal acceptance performs an
  idempotent repository write; no cache refresh is required, keeping API and
  worker replicas coherent without process-local state.

When a method needs non-trivial branching, extract it in this order:

1. Create a domain policy/value object/state machine when the logic is pure.
2. Create an application use case when the logic coordinates repositories,
   tools, gates, workflows, or providers.
3. Create an infrastructure adapter when the logic talks to PostgreSQL, MinIO,
   LLM providers, Temporal/LangGraph, or runners.
4. Keep the router unchanged except for calling the new application method.

## 6. Router Contract

Routers may:

- Resolve services from `request.app.state`.
- Validate primitive path/query/body shape.
- Convert exceptions to HTTP error responses.
- Stream application-provided SSE events.

Routers must not:

- Import `store`.
- Construct concrete application internals such as `AuthService`.
- Execute tool workflows directly.
- Inspect repository internals.
- Apply domain policy decisions.
- Construct SQLAlchemy sessions or ORM records.

## 7. Tool-Native Write Path

Nasus is agent-first and tool-native. Therefore:

- Buttons, cards, forms, chat commands, and external API calls must converge on
  the same tool invocation path for writes.
- High-risk actions must pass RBAC plus confirmation, approval, or policy gates.
- ToolInvocation is the audit spine connecting conversation, AgentGoal, domain
  object, evidence, and approval.
- Application services can expose convenience methods, but those methods must
  still call `ToolInvocationRuntime` for business writes.

## 8. Migration Roadmap

### Phase A: Interface Boundary

- Route modules stop importing global `store`.
- `composition.py` wires application services.
- `composition.py` may set protocol-local state such as `request.state.user`,
  but must not mutate `ApplicationStore` state directly; current-user binding
  goes through `PlatformApplicationService.bind_authenticated_user`.
- Boundary tests enforce router dependency rules.

### Phase B: Platform Extraction

- Move settings, model configuration, auth/RBAC, audit, and tool catalog into
  platform application services and infrastructure adapters.
- Keep account registration, login/logout, avatar updates, and auth error
  mapping behind `AccountApplicationService`; `PlatformApplicationService`
  should remain a delegating facade.
- Keep HTTP authentication request parsing and unified auth error responses in
  `interface/http/auth.py`; app-root `auth.py` is only a compatibility
  re-export, and RBAC/governance rules must stay in platform application/domain
  policies instead of the middleware.
- Keep RBAC role normalization, aliases, ordering, required-role thresholds, and
  denial summaries in `domain/platform/rbac.py`; app-root `rbac.py` is only a
  compatibility re-export.
- Keep project membership and resource authorization behind
  `ProjectAccessApplicationService`. It depends on the authenticated Actor,
  `ProjectAccessRepositoryPort`, and `ProjectAccessReadPort`; it must not retain
  `ApplicationStore` or inspect compatibility projection dictionaries.
  `SQLAlchemyProjectAccessReadModel` reads project existence, conversation and
  ToolInvocation scope, version/US ownership, and invocation-creator audit
  facts from PostgreSQL. `project_role_bindings` remains the durable source for
  effective project roles. Project workspace, ToolInvocation, Agent,
  system-image, and governance paths reuse the same service.
- Keep tool confirmation/approval gate rules in
  `domain/platform/tool_governance.py`; app-root `tool_governance.py` is only a
  compatibility re-export.
- Keep multi-instance LLM, embedding, and rerank configuration behind
  `ModelConfigurationApplicationService`; test tokens, payload fingerprints,
  active route selection, and legacy import rules must not live in
  `ApplicationStore`. The application contracts live in
  `model_configuration_ports.py`; production uses
  `SQLAlchemyModelConfigurationState` to reload committed base settings and
  legacy migration secrets on every request. This prevents stale active routes
  across API replicas. `ProjectedModelConfigurationState` is test/migration-only.
  Store compatibility may only delegate public API-shaped methods to the
  injected service. Settings persistence and API-key encryption adapters belong
  under `infrastructure/persistence`, not in app-root compatibility modules.
- Keep tool catalog reads, ToolInvocation create/confirm/execute/gate entry
  points, invocation filtering, and audit queries behind
  `ToolInvocationApplicationService`; keep the canonical lifecycle runtime in
  `application/platform/runtime.py`, and keep `ApplicationStore` as a delegate.
- Keep `GovernanceToolHandler` as a tool adapter only. Approval request/decision,
  merge resolution, release decision submission, and baseline promotion
  mutations belong behind `GovernanceApplicationService`.
- Keep `QueryToolHandler` as a tool adapter only. It should not inspect
  project/version/conversation internals or construct read-model summaries
  directly; query planning and answer persistence belong behind
  `QueryToolApplicationService`.
- Move reusable read-model summary rules behind `ReadModelSummaryService`.
  Compatibility methods on `ApplicationStore` may delegate to it, but new
  dashboard/project/version/workspace summary logic must not be added to
  `store.py`.
- Keep public `/v1/*` API contracts stable.

### Phase C: System Image Extraction

- Move source registration, ingestion, context materialization, retrieval, and
  baseline operations behind `application/system_image`.
- Keep the system-image retrieval port behind
  `application/system_image/retrieval.py`; app-root `system_image_retriever.py`
  must remain a compatibility re-export only.
- Keep source-binding readiness and missing-source rules behind
  `domain/system_image/source_binding.py`; services and handlers should not
  reimplement the required `code` check or optional `us_doc / test_asset`
  coverage-gap policy inline.
- Keep Official System Image build-state transitions behind
  `domain/system_image/build_state.py`; services should only supply source
  statuses, missing source types, baseline status, context flags, and project
  system image status.
- Keep raw-asset chunk splitting, chunk IDs, chunk kind mapping, content hashes,
  token estimates, and stable hashes behind `domain/system_image/chunking.py`;
  services should only pass extracted text units to the policy and persist the
  returned facts.
- Keep missing quality context, context hashes, confidence, risk, coverage,
  automation feasibility, release score, and risk-driver rules behind
  `domain/system_image/quality_context.py`; services should only provide
  sources, relationships, metrics, and project counters.
- Keep US work item derivation from knowledge objects and default asset-lane
  templates behind `domain/system_image/us_work_items.py`; services should only
  convert the decisions into DTOs and persist them.
- Keep read-model endpoints such as project knowledge, knowledge detail, and
  system image snapshots behind `SystemImageApplicationService` instead of the
  project workspace BFF or inline `ApplicationStore` read aggregation.
- Keep `SystemImageToolHandler` as an interface/tool adapter only; it must not
  call `ApplicationStore`, `_emit_tool_status`, `append_message`, or
  `agent_swarm_coordinator` directly.
- Move pure merge, fork, branch, and source validation rules into
  `domain/system_image`.
- Keep persistence adapters in `infrastructure/persistence`; app-root
  `database.py`, `db_models.py`, `repositories.py`, and `settings_store.py`
  must remain compatibility re-exports only. `ApplicationStore` and all new
  application/infrastructure code must import database setup and repositories
  from `infrastructure.persistence`, never through the app-root facade.
- Keep platform settings and model-provider configuration persistence in
  `infrastructure/persistence/settings_repository.py`.
- Keep Agent conversation, message, goal, memory, swarm, tool-invocation
  projection, and audit-event persistence in
  `infrastructure/persistence/conversation_repository.py`.
- Keep system-image persistence in
  `infrastructure/persistence/system_image_repository.py`.
- Keep quality-loop persistence in
  `infrastructure/persistence/quality_loop_repository.py`.
- Keep project and version read-model persistence in
  `infrastructure/persistence/project_repository.py`. Its system-image and
  quality-loop methods are compatibility delegates only and must not contain
  system-image or quality-loop SQLAlchemy query / ORM mapping implementation.
  The transitional
  `infrastructure/persistence/repositories.py` module may re-export concrete
  repositories for compatibility only; it must not contain SQLAlchemy queries,
  ORM mapping implementation, settings persistence, conversation persistence,
  or new repository methods. Continue splitting remaining repository methods by
  bounded context instead of adding implementation to the aggregate file.
- Keep runtime environment guards in `infrastructure/config`; app-root
  `runtime_config.py` must remain a compatibility re-export only.
- Keep Agent workflow/graph gateway environment configuration in
  `infrastructure/config/agent_runtime_config.py`; app-root
  `agent_runtime_config.py` must remain a compatibility re-export only.
- Keep S3/MinIO/local object storage adapters in `infrastructure/storage`;
  app-root `object_storage.py` must remain a compatibility re-export only, and
  new code must import object-storage adapters from `infrastructure.storage`.
- Keep LLM, embedding, and rerank provider adapters in `infrastructure/llm`;
  app-root `llm.py` must remain a compatibility re-export only, and new code
  must import provider adapters from `infrastructure.llm`.
- Keep runner lifecycle adapters in `infrastructure/runner`; app-root
  `run_orchestrator.py` must remain a compatibility re-export only, and new
  code must import `RunOrchestrator` from `infrastructure.runner`.
  `RunOrchestrator` must receive quality-loop context through an explicit
  provider such as `RunTaskContextProvider`, run/evidence persistence through
  `QualityRunWorkspacePort`, and binary artifact storage through
  `EvidenceObjectStoragePort`. Production persistence belongs in
  `infrastructure/quality_loop/SQLAlchemyQualityRunWorkspace` and must use
  entity-grained run upserts plus run-scoped evidence replacement; runner adapters must
  not retain `ApplicationStore`, call repositories, mutate Store dictionaries,
  or reach through the Store to object storage.

### Phase D: Agent Extraction

- Move conversation, AgentGoal state machine, memory packaging, planner policy,
  and swarm merge policy into `application/agent` and `domain/agent`.
- Keep Agent swarm coordination behind `application/agent/swarm.py`;
  app-root `agent_swarm.py` must remain a compatibility re-export only, and
  swarm event publication must continue to flow through
  `PlatformEventApplicationService`.
- Keep main user-message orchestration behind
  `ConversationMessageApplicationService`; `ApplicationStore.handle_message`
  remains a compatibility delegate only.
- Keep AgentGoal/AgentStep lifecycle transitions behind
  `domain/agent/state_machine.py`; app-root `agent_goal_state_machine.py` must
  remain a compatibility re-export only.
- Keep AgentGoal runtime orchestration behind `application/agent/loop.py`;
  app-root `agent_loop_runtime.py` must remain a compatibility re-export only.
- Keep Agent workflow runtime protocols/wrappers behind
  `application/agent/workflow.py` and runtime selection behind
  `infrastructure/workflow/agent_workflow_factory.py`; app-root
  `agent_workflow_runtime.py` must remain a compatibility re-export only.
- Keep AgentGoal plan compilation behind `application/agent/plans.py`;
  app-root `agent_goal_plan_compiler.py` must remain a compatibility re-export
  only.
- Keep conversation-to-Agent decision planning behind
  `application/agent/planner.py`; app-root `agent_planner.py` must remain a
  compatibility re-export only.
- Keep Agent memory context identity and summaries behind
  `domain/agent/memory.py`; route runtimes and planners should import
  `AgentMemoryContext` from the domain package, not from the compatibility
  `agent_memory.py` manager module.
- Keep Agent memory context assembly behind `application/agent/memory.py`;
  `ApplicationStore` may own the instance during migration, but the manager
  implementation must not live in app-root compatibility modules.
- Keep LLM reply generation and assistant-message persistence behind
  `AgentReplyApplicationService`; `ApplicationStore` must not expose
  `_generate_llm_content`, `_conversation_system_prompt`, or
  `_conversation_context_snapshot`.
- Keep LLM provider access in `infrastructure/llm`.
- Keep workflow adapters in `infrastructure/workflow`.

### Phase E: Quality Loop Extraction

- Keep `ProjectVersionToolHandler` as a tool adapter only; project/version/US
  mutations belong behind `ProjectVersionApplicationService` in
  `application/quality_loop/project_versions.py`.
- Keep project and version record creation behind
  `ProjectVersionApplicationService`; `ApplicationStore.create_project` and
  `ApplicationStore.create_version` may delegate for compatibility but must not
  assemble `ProjectCard`, `VersionSummary`, or release-readiness records inline.
  They must delegate through the constructor-injected `project_versions`
  service instead of constructing `ProjectVersionApplicationService` inside
  methods. That service receives `ProjectVersionWorkspacePort`,
  `QualityLoopContextReadPort`, and `SystemImageOperationsPort`; compatibility
  production state and repository translation stay in
  `infrastructure/quality_loop/SQLAlchemyProjectVersionWorkspace`.
  `LegacyProjectVersionWorkspace` remains available only for isolated tests
  and migration compatibility.
- Keep `application/quality_loop/use_cases.py` focused on
  `QualityLoopApplicationService`. New project setup, version setup, US import,
  owner assignment, version risk, and US task-start changes belong in
  `application/quality_loop/project_versions.py`.
- Keep `QualityLoopToolHandler` as a tool adapter only. Scope, scenario, case,
  automation, failure, healing, release advice, asset-pack refresh, and release
  assessment state transitions belong behind `QualityLoopApplicationService`.
- Keep quality-loop operational DTOs behind
  `application/quality_loop/quality_models.py`; root `models.py` is a
  compatibility re-export during migration, not a place for new model
  definitions.
- Keep release-readiness scoring and blocked-vs-ready decisions behind
  `domain/quality_loop/release_readiness.py`; application services should only
  provide open failures, map decisions into DTOs, and persist them.
  Release-readiness writes and project release-risk synchronization must go
  through `QualityReleaseReadinessApplicationService`.
- Keep default asset-lane templates, lane matching compatibility, quality asset
  part revision increments, QualityAssetPack status transitions, current
  revision calculation, and evidence aggregation behind
  `domain/quality_loop/quality_assets.py`; application services should only
  create DTOs and coordinate persistence. QualityAssetPack writes must go
  through `QualityAssetPackApplicationService`, and lane/US progress writes
  must go through `QualityAssetProgressApplicationService`, not inline code
  inside the main quality-loop use case.
- Keep failure fingerprinting, failure-kind classification, healing depth,
  fallback-to-human, run healing status, and failure root-cause text behind
  `domain/quality_loop/failure_analysis.py`; application services should only
  provide failed runs, existing report counters, evidence refs, and persistence.
  Failure report writes and run healing synchronization must go through
  `QualityFailureReportApplicationService`.
- Keep quality-loop metric materialization into system-image snapshots and
  overlays behind `QualityImageUpdateApplicationService`;
  `QualityStepCompletionApplicationService` should request metric
  materialization, while `QualityLoopApplicationService` should not construct
  system-image DTOs or call system-image repositories directly.
- Continue moving pure US work item, quality asset pack, run lifecycle, failure
  analysis, release readiness, and approval policies from the application
  service into `domain/quality_loop`.
- Compose production governance through `SQLAlchemyGovernanceWorkspace`.
  Approval, release, merge, evidence, project, version, and task reads must use
  committed PostgreSQL facts. `SQLAlchemyGovernanceCommandRepository` owns the
  atomic approval write plus synchronization of project/version pending counts.
  Governance application services perform entity-level saves and must not
  replace complete approval or version collections. The compatibility
  governance workspace is test/migration-only.

### Phase F: Compatibility Facade Removal

- `ApplicationStore` no longer owns business workflows.
- `models.py` is split by bounded context and layer; root persistence
  compatibility modules are removed after all callers import infrastructure
  ports/adapters directly. The app-root `models.py` barrel remains free of
  class definitions until it can be deleted.
- Tests cover domain, application, infrastructure, and interface independently.

## 9. Verification

Required checks for backend architecture changes:

```bash
./.venv/bin/python -m pytest tests/test_ddd_boundaries.py -q
./.venv/bin/python -m pytest apps/api/tests/test_api.py apps/api/tests/test_runtime_config.py -q
```

For full V1 confidence, also run:

```bash
npm run test:portal-boundaries
npm run build:portal
npm run test:smoke
```
