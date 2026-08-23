# Nasus Backend DDD Boundaries

Nasus backend code is organized around product domains, not framework layers alone.

## Current Migration State

The backend is in a **progressive DDD migration**. The directory structure and
HTTP boundary are in place. Process-local dependency wiring currently lives in
`RuntimeAssembly`; Store-shaped compatibility methods live in the separate
`ApplicationRuntime` wrapper.

Production composition must resolve `RuntimeAssembly` through
`get_runtime_assembly()` and expose only application services through
`ApplicationContainer`. `ApplicationRuntime`, `ApplicationStore`,
`get_application_runtime()`, and `get_application_store()` are legacy
compatibility surfaces retained for migration tests and old imports. The
compatibility wrapper must reuse the production `RuntimeAssembly`; constructing
a second dependency graph would split event queues, provider gateways, and
process-local coordination state.

This is intentional for V1 stability:

- HTTP routers must call application services from `request.app.state`.
- HTTP authentication middleware must live under `interface/http`; app-root
  `auth.py` is a compatibility import only.
- Application services must not delegate to `ApplicationRuntime`. The
  compatibility direction is one-way: facade methods may call application
  services, while application services depend only on declared ports. The
  `system_image`, Agent lifecycle/memory/swarm, quality-loop workspace, and
  platform project-workspace slices already follow this rule.
- New business rules must not be added to `interface/http/routers` or
  `interface/http/auth.py`.
- New use cases should enter `application/<domain>` first, even when their first
  implementation delegates to the facade.
- `store.py` is the temporary host for `RuntimeAssembly` and the compatibility
  facade; it must contain composition/delegation only and must not receive new
  business rules. `models.py`, and app-root `auth.py` / `auth_service.py` / `database.py` /
  `db_models.py` / `repositories.py` / `settings_store.py` /
  `runtime_config.py` / `agent_runtime_config.py` / `object_storage.py` /
  `llm.py` / `run_orchestrator.py` / `system_image_service.py` /
  `source_ingestion.py` / `context_extraction.py` /
  `conversation_orchestrator.py` /
  `system_image_tool_catalog.py` /
  `agent_graph_runtime.py` / `tool_invocation_runtime.py` /
  `tool_invocation_handlers.py` /
  `system_image_tool_handlers.py` / `project_version_tool_handlers.py` /
  `quality_loop_tool_handlers.py` / `governance_tool_handlers.py` /
  `query_tool_handlers.py` / `temporal_agent_gateway.py` /
  `langgraph_agent_gateway.py` are compatibility
  surfaces, not preferred homes for new business logic. Real runtime
  environment validation and Temporal/LangGraph gateway env config live under
  `infrastructure/config`; real ORM records, unit-of-work helpers,
  repository/database adapters, and settings persistence adapters live under
  `infrastructure/persistence`; real object storage adapters live under
  `infrastructure/storage`; real LLM/embedding/rerank provider adapters live
  under `infrastructure/llm`; real execution runner adapters live under
  `infrastructure/runner`; real Temporal/LangGraph workflow gateways and
  workflow workers live under `infrastructure/workflow`.
  New code, including `RuntimeAssembly` wiring and `ApplicationRuntime`
  compatibility delegates, must import
  database setup and repositories from `infrastructure.persistence`, not through
  the app-root persistence re-export modules.
  Platform settings and model-provider configuration persistence live in
  `infrastructure/persistence/settings_repository.py`. Agent conversation,
  message, goal, memory, swarm, tool-invocation projection, and audit-event
  persistence live in `infrastructure/persistence/conversation_repository.py`.
  System-image persistence lives in
  `infrastructure/persistence/system_image_repository.py`. Quality-loop
  persistence lives in `infrastructure/persistence/quality_loop_repository.py`.
  Project and version read-model persistence currently live in
  `infrastructure/persistence/project_repository.py`; its system-image and
  quality-loop methods are compatibility delegates only. The legacy
  `infrastructure/persistence/repositories.py` module is a compatibility export
  only; it must not contain SQLAlchemy query implementation, ORM mapping logic,
  settings persistence, conversation persistence, or new repository methods.
  Runner lifecycle adapters must be imported from `infrastructure.runner`, not
  through app-root runner compatibility re-export modules. Runner adapters may
  receive application/domain context through explicit provider protocols such
  as `RunTaskContextProvider`, but must not call or reintroduce
  `ApplicationStore` private quality-loop context helpers such as
  `_current_task_context`.
  LLM/embedding/rerank and object-storage adapters must be imported from
  `infrastructure.llm` and `infrastructure.storage`, not through app-root
  compatibility re-export modules.
  HTTP authentication request parsing and error response mapping live under
  `interface/http/auth.py`.
- App-root `models.py` is a compatibility re-export barrel only. It must not
  define Pydantic models, domain objects, request DTOs, response DTOs, or
  cross-domain read models. New contracts belong in the owning bounded context,
  such as `application/agent/agent_models.py`,
  `application/system_image/system_image_models.py`,
  `application/quality_loop/quality_models.py`,
  `application/platform/project_models.py`, `application/platform/read_models.py`,
  `application/platform/model_settings.py`, `application/platform/account_models.py`,
  or `application/platform/tool_models.py`. Internal backend code must import
  from those owning modules instead of from `models.py`.
- App-root modules are not implementation homes. Except for `main.py`,
  `composition.py`, `store.py`, and the transitional `models.py` compatibility
  barrel, every `apps/api/app/*.py` file must stay as a tiny relative
  `import *` re-export only. Do not add classes, functions, settings reads,
  ORM queries, HTTP request handling, LLM calls, object storage calls, or
  workflow adapter code to the app root. Add or move implementation code under
  the owning `interface`, `application`, `domain`, or `infrastructure` package
  first, then expose a root compatibility alias only if legacy imports still
  require it.

## Layers

- `interface`: FastAPI controllers and SSE adapters. This layer converts protocol payloads into application calls and maps exceptions to HTTP responses.
- `application`: use cases, commands, queries, orchestration, and ports. Cross-domain calls must go through this layer.
- `domain`: pure entities, value objects, policies, state machines, and domain services. Domain code must not import ORM, LLM clients, object storage, Temporal, FastAPI, or environment configuration.
- `infrastructure`: adapters for PostgreSQL, runtime environment validation,
  object storage, LLM/embedding/rerank providers, workflow engines, and runners.
- `composition.py`: dependency assembly. It wires interface routes and adapters without owning business rules.

## Product Boundaries

- `system_image`: source registration, ingestion, context materialization, baseline/branch, retrieval, embedding, and rerank.
- `agent`: conversation, agent goal, agent step, memory, planner, and swarm behavior.
- `quality_loop`: US task, quality profile, quality asset pack, run, evidence, failure analysis, release readiness, and release decision.
- `platform`: auth/RBAC, settings, tool catalog, tool invocation, governance gates, audit events, and SSE outbox.

## Dependency Rules

- `interface -> application -> domain`
- `infrastructure -> application/domain` only through declared ports or repository interfaces.
- Product domains do not directly import another product domain's repository.
- Write operations remain traceable through `ToolInvocationRuntime`.
- Project workspace HTTP reads must use `ProjectWorkspaceReadPort`; they must
  not call `ProjectReadModelRefreshApplicationService`, retain
  `ApplicationStore`, or read its projection dictionaries. The infrastructure
  cross-domain read adapter may compose repositories because it is a read-only
  BFF projection, while all writes continue through Tool Invocation use cases.
- Welcome, Build, Dashboard, and Documentation reads must use
  `TopLevelContentReadPort`. Production composition binds that port to
  `SQLAlchemyTopLevelContentReadModel`, which performs fresh PostgreSQL reads
  and applies project visibility on every request. Process-local compatibility
  projections and demo seed state are not valid portfolio sources of truth.
- Agent query tools must use `AgentQueryReadPort`. Production composition binds
  this port to `SQLAlchemyAgentQueryReadModel`, which reads PostgreSQL facts and
  filters every project, conversation, quality, and memory query by the current
  actor's durable project bindings. Agent summaries must not read the shared
  compatibility projection dictionaries.
- High-risk actions remain behind RBAC plus confirmation, approval, or policy gates.
- System-image source ingestion owns policy and state transitions in
  `application/system_image/source_ingestion.py`, but accesses the transitional
  write workspace only through `SystemImageIngestionProjectionPort`.
  Project-scoped advisory locking, repository persistence, and read-boundary
  notification are
  implemented by
  `infrastructure/system_image/ingestion_projection.py`. Application ingestion
  code must not import or retain `ApplicationStore`.
- All system-image application state, persistence, object storage, embedding,
  rerank, project-access, and read-model refresh operations enter through
  `application/system_image/ports.py`. The production adapter is
  `infrastructure/system_image/SQLAlchemySystemImageWorkspace`: PostgreSQL is
  its source of truth and request-local snapshots exist only until the explicit
  `persist_system_image` boundary. `LegacySystemImageWorkspace` remains a test
  and migration compatibility adapter and must not be selected by production
  composition. Both adapters receive repositories, provider clients, model
  settings/key providers, access policy, read-model refresh, and object storage
  as explicit constructor dependencies; neither may discover `ApplicationStore`.
- Production project, system-image, and quality-loop reads are PostgreSQL
  read-through queries. The composition root must not hydrate shared project
  mappings or compose `SystemImageProjectionState`. The legacy
  `ProjectStateLoaderApplicationService` and
  `CompatibilityProjectReadModelProjection` remain migration-test fixtures
  only.
- Production Agent context retrieval uses
  `SQLAlchemySystemImageRetriever`. It loads a project-scoped durable snapshot,
  generates a query vector through the selected embedding route, queries the
  PostgreSQL FTS/pgvector hybrid index, reranks candidates through the selected
  rerank route, and atomically appends `RetrievalRun` plus `RerankRecord`
  evidence. It depends only on repositories and application ports and must not
  retain `ApplicationStore` or compatibility projection dictionaries.
  `DefaultSystemImageRetriever` is migration/test-only and must not be selected
  by production composition.
- `CompatibilitySystemImageIngestionProjection` receives a project-keyed
  mutation-guard factory, workspace port, and read-model refresh service. In
  production the guard is `SQLAlchemyProjectMutationLock`, backed by a
  PostgreSQL advisory transaction lock. It must not retain the composition
  facade; synchronization is a constructor-injected infrastructure
  concern.
- `SystemImageService` and `SystemImageApplicationService` are assembled once
  in `ApplicationStore` through that adapter. Agent memory, quality-loop,
  governance, tool runtime, and HTTP composition must reuse the assembled
  system-image boundary rather than constructing a Store-backed system-image
  service.
- RBAC role normalization and tool-required-role policy live in
  `domain/platform/rbac.py`; runtimes may call this policy but must not own
  role threshold rules inline.
- Project membership and resource authorization enter through
  `ProjectAccessApplicationService`, `ProjectAccessRepositoryPort`, and
  `ProjectAccessReadPort`. The service resolves the authenticated Actor from
  request/workflow context and must not retain `ApplicationStore` or read its
  project, conversation, ToolInvocation, audit, version, or US dictionaries.
  `SQLAlchemyProjectAccessReadModel` is the production adapter for project
  existence and resource-scope facts; `project_role_bindings` remains the
  durable source for effective project roles. HTTP, Agent, governance,
  system-image, and ToolInvocation paths must reuse this boundary.
- Tool confirmation and approval gate policy live in
  `domain/platform/tool_governance.py`; runtimes may call this policy but must
  not own waiting-confirmation or waiting-approval branching rules inline.
- The canonical `ToolInvocationRuntime` depends only on the explicit contracts
  in `application/platform/runtime_ports.py`. Invocation projection state,
  catalog lookup, project-scoped authorization, governance policy, audit
  writes, Agent replies, SSE updates, and handler dispatch are constructor
  dependencies. `application/platform/runtime.py` must not import, retain, or
  construct `ApplicationStore` or discover collaborators through Store
  attributes. The compatibility projection is translated by
  `infrastructure/platform/tool_runtime.py`, and the composition root owns
  handler-registry construction.

- ToolInvocation and AuditEvent query use cases must read committed facts from
  the shared persistence boundary. API and Temporal worker processes do not
  share Python projections, so production composition uses
  `SQLAlchemyToolInvocationApplicationState` backed by
  `ConversationRepository`. `ProjectedToolInvocationApplicationState` remains
  available only for isolated tests and migration adapters; it must not be
  restored as the production HTTP query source.
- `tests/test_ddd_boundaries.py` enforces backend import direction with an AST
  import-boundary scan: `domain` must not import `application`,
  `infrastructure`, or `interface`; `application` must not import `interface`;
  `interface` must not import `infrastructure` directly. When a new dependency
  is needed, introduce an application service, domain policy input, or
  infrastructure adapter instead of bypassing the layer boundary.
- Agent message writing, conversation summary checkpoints, AgentGoal
  explanations, planner context, and system-image plan compilation depend on
  explicit protocols from `application/agent/ports.py`. They must not import
  `ApplicationStore`, read compatibility projection dictionaries, call
  repositories, or construct platform event services directly.
- Agent planning infrastructure is also explicit:
  `LegacyAgentPlanStateAdapter` receives `AgentPlanningProjectionState` plus
  `AgentPlanningRuntimeAdapters`, and `LegacyAgentPlannerContextAdapter`
  receives `AgentPlannerContextAdapters`. Neither adapter may retain
  `ApplicationStore`. Project/system-image facts, tool-catalog reads, memory
  context, quality state, and fallback summaries are constructor dependencies.
  Shared projection dictionaries must exist before these planning ports are
  assembled.
- Conversation lifecycle, message orchestration, AgentGoal lifecycle, and
  AgentGoal conversation projection enter through
  `ConversationManagementStatePort`, `ConversationMessageRuntimePort`,
  `AgentGoalLifecycleStatePort`, and `AgentGoalProjectionStatePort`.
  `application/agent/conversations.py`, `messages.py`, `lifecycle.py`, and
  `goal_projection.py` must not retain Store escape hatches, resolve project
  scope from compatibility dictionaries, invoke repositories, or construct
  concrete Planner/Tool/Goal/Audit/Event services directly.
- `LegacyConversationManagementStateAdapter` is assembled from
  `AgentConversationManagementProjectionState`,
  `AgentConversationManagementPersistenceAdapters`, and
  `AgentConversationManagementRuntimeAdapters`. It must not retain
  `ApplicationStore`. Project/version/US lookup enters through
  `ProjectScopeReadPort`. Production composition binds this port to
  `infrastructure/platform/SQLAlchemyProjectScopeReadModel`, which resolves
  hierarchy ownership from PostgreSQL for every request or worker execution.
  `CompatibilityProjectScopeProjection` is test/migration-only.
- Conversation merge relationships are durable facts. They are persisted as
  `ConversationLinkRecord` rows through `ConversationRepository` and hydrated
  into the shared projection during runtime startup/refresh; process-local-only
  conversation links are not permitted.
- Main conversation orchestration is translated by
  `LegacyConversationMessageRuntimeAdapter`, which receives
  `AgentConversationRuntimeAdapters`. The adapter must not retain
  `ApplicationStore`; message persistence, Planner calls, tool creation and
  confirmation, goal lifecycle, governance checks, projection, and audit
  recording are explicit command/query dependencies.
- Conversation message persistence, summary checkpoint persistence, canonical
  conversation SSE publication, and AgentGoal explanation reads are assembled
  through `AgentConversationProjectionState`,
  `AgentConversationPersistenceAdapters`,
  `AgentConversationCheckpointAdapters`, `AgentConversationEventAdapters`, and
  `AgentGoalExplanationAdapters`. Their infrastructure adapters must not retain
  `ApplicationStore` or construct event/repository services. Compatibility
  projections and lazy cross-application callbacks are wired only in the
  composition boundary.
- The outer Agent loop and Think/Act/Observe/Decide graph depend only on
  `AgentLoopStatePort` and `AgentGraphStatePort`. `application/agent/loop.py`
  and `graph.py` must not retain `ApplicationStore`, construct platform event
  or goal-projection services, or import infrastructure workflow factories.
  Graph runtime selection and LangGraph construction belong under
  `infrastructure/workflow`; the Store composition root injects the selected
  graph runtime into the loop.
- `LegacyAgentGraphStateAdapter` is assembled from
  `AgentGraphLookupAdapters`, `AgentGraphToolRuntimeAdapters`,
  `AgentGraphMemoryAdapters`, and the shared `AgentGoalLifecycleAdapters`.
  The adapter must not retain `ApplicationStore` or discover graph
  dependencies dynamically. Goal reads, ToolInvocation commands, catalog
  reads, audit/SSE/message effects, and memory operations remain distinct
  constructor dependencies so the graph can be tested and replaced without a
  compatibility-store escape hatch.
- Agent memory depends only on `AgentMemoryStatePort`,
  `SystemImageRetriever`, and `SystemImageWorkspacePort`.
  `application/agent/memory.py` must not retain `ApplicationStore`, read
  compatibility projection dictionaries, call repositories, or construct
  platform event services. Compatibility projections and persistence are
  translated by `infrastructure/agent/LegacyAgentMemoryStateAdapter`.
- `LegacyAgentMemoryStateAdapter` is assembled from
  `AgentMemoryProjectionState`, `AgentMemoryPersistenceAdapters`,
  `AgentMemoryRuntimeAdapters`, `AgentMemoryEventAdapters`, and dedicated
  candidate/workspace compatibility query objects. It must not retain
  `ApplicationStore`. Project, version, US, run, approval, and candidate
  knowledge projection mapping belongs to
  `memory_state_dependencies.py`, while the adapter only implements the
  application port and coordinates durable writes/events.
- Agent swarm coordination depends only on `AgentSwarmStatePort` and a
  replaceable `AgentWorkerExecutionPort`. `application/agent/swarm.py` must
  not retain `ApplicationStore`, call repositories, or construct platform
  event services. Swarm projections and SSE/outbox effects are translated by
  `infrastructure/agent/LegacyAgentSwarmStateAdapter`.
- `LegacyAgentSwarmStateAdapter` is assembled from
  `AgentSwarmProjectionState`, `AgentSwarmPersistenceAdapters`, and
  `AgentSwarmEventAdapters`. It must not retain `ApplicationStore`; durable
  projection updates, repository writes, and canonical conversation/swarm SSE
  publication remain separate dependencies.
- Project, version, and US onboarding use cases depend on
  `ProjectVersionWorkspacePort`, `QualityLoopContextReadPort`, and
  `SystemImageOperationsPort`. `application/quality_loop/project_versions.py`
  and `version_context.py` must not retain `ApplicationStore`, compatibility
  dictionaries, or repositories. Production composition binds this port to
  `infrastructure/quality_loop/SQLAlchemyProjectVersionWorkspace` and uses
  entity-grained project/version/US writes. `LegacyProjectVersionWorkspace`
  is retained only for isolated tests and migration compatibility.
- Production quality-loop context, scope resolution, asset progress,
  asset-pack persistence, run execution, and failure analysis use the
  `SQLAlchemy*Workspace` adapters and canonical repositories directly.
  `QualityLoopProjectionState` and `QualityLoopWorkspaceAdapters` are retained
  only by isolated legacy-adapter tests and must not be assembled by the
  production composition root. No adapter under `infrastructure/quality_loop`
  may import, retain, or discover dependencies through `ApplicationStore`.
- Temporal workflow state synchronization enters through
  `AgentWorkflowStatePort`. Infrastructure workflow factories must not recover
  the Store through `loop_runtime.store`; workflow IDs and remote goal
  projections are supplied explicitly by the anti-corruption adapter.
- Production workflow synchronization is implemented by
  `SQLAlchemyAgentWorkflowState`. Workflow identifiers and returned AgentGoal
  facts are read and committed through `ConversationRepository`; it must not
  rely on process-local projection refresh before the fact is visible.
- Cross-process worker result acceptance is owned by
  `DistributedStateSynchronizationApplicationService`, assembled from
  `DistributedStateSynchronizationDependencies`. It validates the durable
  Conversation, commits AgentGoal idempotently, and refreshes only the
  remaining project read model. It must not hydrate Agent runtime facts or
  import or retain `ApplicationStore`.
- `infrastructure/agent/SQLAlchemyAgentApplicationPorts` is the production
  Agent adapter composition. Conversation, AgentGoal, memory, swarm, summary,
  and planning facts are loaded from PostgreSQL or their owning bounded-context
  repositories on every use-case read. `LegacyAgentApplicationPorts` remains
  available only for isolated migration tests and is not assembled by Store.
  Conversation, ConversationLink, and AgentGoal are PostgreSQL-only facts,
  including Temporal worker result synchronization. Production composition
  must not mirror Conversation into `ApplicationStore`.
  ConversationSummaryCheckpoint and SessionKnowledgeBinding are PostgreSQL-only
  facts and must not be copied into Store or process-local runtime mappings.
- The canonical Tool Registry remains complete, but planner memory uses
  `application/agent/tool_context.py` to package all available tool IDs plus a
  bounded set of detailed, scope- and intent-relevant contracts. Domain memory
  summaries only recognize strict `[section_name]` headers and must never echo
  serialized tool payloads into AgentStep metadata.
- `application/system_image/retrieval.py` defines the Agent-facing
  `SystemImageRetriever` port and result contract only. Concrete projection,
  vector, graph, or external code-memory implementations belong under
  `infrastructure/system_image`; application code must receive the retriever
  through constructor injection and must not select an infrastructure adapter.

## Domain Purity Rules

Domain modules may import Python standard library modules and other modules
under `apps/api/app/domain` through relative imports.

Domain modules must not import:

- FastAPI, SQLAlchemy, Pydantic, HTTP clients, or environment configuration.
- `ApplicationStore`, repositories, ORM models, or compatibility facade modules.
- Object storage, LLM, embedding/rerank, Temporal/LangGraph, runner, tool runtime, or handler adapters.

Use `Protocol` inputs when a policy needs data from another layer. Application
services gather concrete data, call domain policies, map the decision into API
DTOs, and coordinate persistence.

## HTTP Boundary Rules

Routers may:

- Parse path, query, and request body values.
- Accept command request bodies as explicit application DTOs.
- Receive application services through typed dependency aliases from
  `interface/http/dependencies.py`.
- Map `KeyError`, validation failures, and policy failures to HTTP errors.
- Return streaming responses from application-provided event iterators.

Routers must not:

- Import the global `store`.
- Read `request.app.state` directly. Only `interface/http/dependencies.py` may
  resolve application services from `request.app.state`.
- Construct concrete services such as `AuthService`.
- Construct domain objects directly for write operations.
- Accept command request bodies as raw `dict` payloads and parse business
  fields inline.
- Reach into repository or ORM classes.
- Implement branching business workflows.
- Call LLM, object storage, workflow runtime, or runner adapters directly.

HTTP auth middleware may:

- Parse Authorization headers and public-path exemptions.
- Map authentication failures to the unified HTTP error response body.
- Resolve platform account sessions through the platform authentication service.
- Bind the authenticated user only by calling
  `PlatformApplicationService.bind_authenticated_user`; this keeps the
  composition root from mutating the compatibility store directly.

HTTP auth middleware must not:

- Own RBAC, approval, or governance policy rules.
- Mutate project, system-image, agent, or quality-loop facts.
- Assign `store.user` or any other `ApplicationStore` state directly; current
  user binding is an application-layer platform account use case.
- Call LLM, object storage, workflow runtime, or runner adapters directly.

## Application Service Pattern

Use cases should follow this package shape:

```text
application/<bounded_context>/
  __init__.py
  use_cases.py              # command/query methods called by routers
  ports.py                  # repository/provider/workflow protocols when needed
  dto.py                    # application-only request/response DTOs when API models are not enough
```

Current compatibility services:

- `application/platform/AccountApplicationService`: account profile,
  registration, login/logout, avatar upload/preset selection, avatar content
  reads, and identity-provider error mapping. It depends only on
  `CurrentUserProviderPort` and `AccountIdentityPort`; it must not retain
  `ApplicationStore` or construct an identity implementation. The bootstrap
  container injects the request-local actor adapter and the PG/MinIO-backed
  identity service. `PlatformApplicationService` is only a facade for
  these account use cases and must not regain direct `AuthService`, avatar
  storage branching logic, or direct `ApplicationStore` state mutation. HTTP
  auth middleware must call this boundary through a token authenticator
  callback and `bind_authenticated_user` instead of constructing concrete auth
  services or assigning `store.user`.
- `application/platform/account_models.py`: platform account and authentication
  contract types for user profile, register/login payloads, session response,
  and avatar update payloads. App-root `models.py` may re-export these names
  during migration, but HTTP auth, platform routes, account services, and store
  compatibility code must import them from this application-layer contract.
- `application/platform/auth_service.py`: stable authentication result and
  error contracts only. PostgreSQL identity/session persistence, password
  hashing, and MinIO avatar storage belong to
  `infrastructure/platform/SQLAlchemyAccountIdentityService`, which implements
  `AccountIdentityPort`. Application account use cases must not import ORM or
  storage implementations. App-root `auth_service.py` is a compatibility alias
  only.
- `application/agent/AgentApplicationService`: HTTP-facing Agent application
  facade for conversation, AgentGoal, Agent memory, Agent events, and swarm
  use cases. It must compose dedicated application services such as
  `ConversationManagementApplicationService`,
  `ConversationMessageApplicationService`,
  `AgentGoalLifecycleApplicationService`, `AgentMemoryManager`,
  `AgentSwarmCoordinator`, and `PlatformEventApplicationService`; it must not
  keep a `self._store` escape hatch or call `ApplicationStore` lifecycle,
  stream, or swarm methods directly. Agent-owned runtime helpers, including
  system-image materialization swarm startup, must live here instead of in
  system-image tool handlers.
- `application/agent/agent_models.py`: Agent application contract types for
  `SpaceType`, `ConversationSession`, `ConversationMessage`,
  `ConversationSummaryCheckpoint`, `ConversationLink`,
  `SessionKnowledgeBinding`, `AgentGoal`, `AgentStep`, `AgentMemoryItem`,
  `AgentMemoryLink`, `AgentSwarmRun`, `AgentWorkerAssignment`, and the
  conversation/Agent request DTOs. App-root `models.py` may re-export these
  names during migration, but Agent application services, workflow adapters,
  persistence adapters, HTTP Agent/conversation routes, and system-image
  retrieval ports must import them from this agent contract instead of adding
  Agent DTOs back to the global model bucket. The `application/agent` package
  must keep lazy exports because `models.py` re-exports this contract during
  migration.
- `application/agent/AgentGoalLifecycleApplicationService`: AgentGoal lifecycle
  coordination above the concrete workflow runtime: active-goal guard, manual
  creation, canonical AgentGoal record creation, default step construction,
  goal read/checkpoint projection, existence checks, resume, interrupt,
  feedback, and active-goal lookup. The root
  `agent_service.py` module is a compatibility alias only, and
  `ApplicationStore.create_agent_goal` is a compatibility delegate only; neither
  surface may regain AgentGoal construction, default AgentStep construction, or
  lifecycle branching logic. `ApplicationStore.get_agent_goal` and
  `ApplicationStore.get_agent_goal_checkpoint` are compatibility delegates only;
  goal lookup and checkpoint projection must stay behind
  `AgentGoalLifecycleApplicationService` instead of reading `agent_goals` or
  workflow runtime internals from the store facade. Lifecycle event publication must go through
  `PlatformEventApplicationService`; this service must not call
  `ApplicationStore._push_event` or `ApplicationStore._push_goal_event`
  directly.
- `application/agent/AgentGoalProjectionApplicationService`: the single
  application-layer writer for keeping `ConversationSession.agent_goals`
  aligned with persisted `AgentGoal` facts. Lifecycle services, graph runtime,
  message orchestration, Temporal workflow sinks, and compatibility store
  methods must call this service instead of duplicating conversation projection
  rules or calling `ApplicationStore._upsert_goal_in_conversation` directly.
  `ApplicationStore._upsert_goal_in_conversation` is a compatibility delegate
  only. During the compatibility phase, `ApplicationStore` must hold a
  constructor-injected `agent_goal_projection` instance and delegate to it
  directly; it must not instantiate this service inside projection methods.
- `infrastructure/agent/goal_state_dependencies.py`: explicit anti-corruption
  dependencies for AgentGoal projection, lifecycle, and outer-loop adapters.
  Conversation projection receives only `AgentGoalProjectionState`; lifecycle
  commands receive the separate `AgentGoalLifecycleState`; repository writes,
  audit, assistant messages, SSE publication, and loop-level service lookups
  are injected through `AgentGoalProjectionPersistenceAdapters`,
  `AgentGoalLifecycleAdapters`, and `AgentLoopRuntimeAdapters`. The
  infrastructure adapters may not retain `ApplicationStore` or discover these
  collaborators dynamically. `LegacyAgentApplicationPorts` receives the
  outer projection, persistence, and runtime dependency records defined in
  `infrastructure/agent/application_port_dependencies.py` and expands them into
  these narrow records while the compatibility facade is retired.
- `application/agent/AgentGoalExplanationApplicationService`: AgentGoal
  explanation read-model assembly for current/blocked step, waiting reason,
  next action, reasoning summary, memory refs, tool invocation refs, and audit
  refs. This read-side packaging must stay separate from lifecycle command
  methods. It must obtain AgentGoal state and checkpoint projection through
  `AgentGoalLifecycleApplicationService` instead of direct `agent_goals` reads
  or workflow-runtime calls. Legacy `ApplicationStore.get_agent_goal_explanation` is a
  compatibility delegate only and must not regain inline step explanation or
  waiting-on branching logic.
  AgentGoal explanation memory refs must be read through `AgentMemoryManager`
  via `ApplicationStore.list_agent_memory_items`, not by scanning
  `ApplicationStore.agent_memory_items` directly.
  Agent application services must obtain ToolInvocation facts through
  the platform ToolInvocation application boundary
  (`ApplicationStore.get_tool_invocation` and
  `ApplicationStore.list_tool_invocations` compatibility delegates during
  migration), not by reading `ApplicationStore.tool_invocations` directly.
- `application/agent/workflow.py`: Agent workflow runtime protocol plus
  Local/Temporal runtime wrappers. It must not read environment variables or
  import Temporal SDK adapters; deployment/runtime selection lives in
  `infrastructure/workflow/agent_workflow_factory.py`.
- `application/agent/graph.py`: AgentGoal graph runtime protocol plus
  Local/LangGraph graph runtime wrappers. It owns Think/Act/Observe/Decide
  execution semantics, planned tool execution, memory binding, and graph-facing
  step assembly, but it must not read environment variables or import concrete
  LangGraph gateway adapters. Runtime selection lives in
  `infrastructure/workflow/agent_graph_factory.py`. Runtime delta events
  (`runtime.thinking.delta`, observation, decision, and goal updates) must be
  published through `PlatformEventApplicationService`, not store private event
  methods. ToolInvocation result lookup for memory projection must use the
  platform application boundary, not the store's internal invocation map.
- `application/agent/loop.py`: AgentGoal runtime application orchestration,
  including conversation binding, AgentGoal creation, audit/event emission,
  kickoff assistant messages, and delegation to the graph runtime. The root
  `agent_loop_runtime.py` module is a compatibility alias only. Runtime-level
  conversation events must be published through `PlatformEventApplicationService`
  instead of `ApplicationStore._push_event`.
- `application/agent/ConversationMessageApplicationService`: main
  conversation message orchestration, including source-binding replies,
  confirmation dispatch, planner decision routing, AgentGoal startup, tool
  invocation creation, and query-answer fallback dispatch. Confirmation-driven
  AgentGoal resume checks must call `AgentGoalLifecycleApplicationService`
  through the agent service boundary instead of reading
  `ApplicationStore.agent_goals` directly. Legacy
  `ApplicationStore.handle_message`,
  `ApplicationStore._pending_confirmation_invocation`,
  `ApplicationStore._handle_confirmation_message_if_any`, and
  `ApplicationStore._handle_source_binding_message_if_any` are compatibility
  delegates only and must not regain planner, confirmation, source-binding, or
  tool-plan branching logic. During the compatibility phase,
  `ApplicationStore` must hold a constructor-injected
  `conversation_messages` instance and delegate to it directly; it must not
  expose `_conversation_message_app` factories or create this service inside
  message-handling methods.
- `application/agent/ConversationFallbackApplicationService`: agent-facing
  fallback response boundary used when the planner does not return a direct
  answer. Conversation message use cases must call this service instead of
  constructing `ReadModelSummaryService` through `ApplicationStore` or
  assembling read-model fallback text inline. `ApplicationStore` must not expose
  `_read_model_summaries`.
- `application/agent/AgentPlannerContextApplicationService`: planner context
  assembly boundary. It owns deterministic planner memory context packaging,
  conversation summary fallback lookup, and current quality-state delegation.
  Planner quality state must be read through
  `QualityLoopContextQueryApplicationService`, not direct `us_items` or
  `asset_lanes` reads from the Agent package. `ApplicationStore` may pass these
  callables into `DeterministicAgentPlanner` and `LLMStructuredAgentPlanner`,
  but it must not keep `_planner_memory_context`,
  `_conversation_summary_fallback`, or `_quality_state_for_planner` private
  methods.
- `application/agent/ConversationMessageWriterApplicationService`: canonical
  conversation message write boundary. It owns `ConversationMessage` and
  `MessageBlock` creation, conversation last-message/status projection,
  repository persistence, automatic summary checkpoint triggering, and
  `conversation.message.created` event publication. `ApplicationStore.append_message`
  is a compatibility delegate only and must not regain DTO construction,
  repository writes, or SSE emission.
- `application/agent/ConversationManagementApplicationService`: conversation
  lifecycle and discovery use cases, including scope resolution, create-or-get,
  listing/filtering, search hits, message pagination, archive/unarchive, and
  merge/link creation. Project/version/US scope lookup for conversation
  creation must be delegated to
  `application/platform/ProjectScopeResolutionApplicationService`, not direct
  `versions` or `us_items` reads from the Agent package. Legacy
  `ApplicationStore` conversation lifecycle methods are compatibility delegates
  only and must not regain inline conversation creation, filtering, search,
  archive, or merge rules. During the
  compatibility phase, `ApplicationStore` must hold a constructor-injected
  `conversation_management` instance and delegate to it directly; it must not
  expose `_conversation_management_app` factories or create this service inside
  conversation lifecycle methods.
- `application/agent/ConversationSummaryCheckpointService`: long-running
  conversation summary checkpoint policy, including eligible message selection,
  latest checkpoint lookup, incremental message range calculation, compact
  summary text construction, and checkpoint DTO assembly.
- `application/agent/ConversationSummaryCheckpointApplicationService`:
  summary checkpoint write use cases, including duplicate checkpoint detection,
  repository persistence, conversation latest-checkpoint projection, and
  `conversation.summary.updated` event publication. `ApplicationStore` may keep
  the in-memory dictionaries during migration, but it must call this service
  instead of owning checkpoint persistence or SSE emission.
- `application/agent/AgentMemoryManager`: Agent memory application boundary for
  LLM memory package construction, API-facing memory context views, explicit
  memory checkpoints, project long-term memory views, candidate memory views,
  reusable `AgentMemoryItem` / `AgentMemoryLink` persistence, and memory item
  queries used by Agent read models. Legacy
  `ApplicationStore.get_agent_memory_context`,
  `ApplicationStore.create_agent_memory_checkpoint`, and
  `ApplicationStore.record_agent_memory_item` are compatibility delegates only;
  `ApplicationStore.list_agent_memory_items` is also a compatibility delegate
  only. These store methods must not regain context hash/summary calculation,
  checkpoint emission, memory filtering, or memory link creation logic.
  Production `AgentMemoryItem` and `AgentMemoryLink` facts are written and read
  only through `SQLAlchemyAgentMemoryState` and `ConversationRepository`.
  They must not be mirrored into `ApplicationStore` dictionaries or restored by
  startup hydration; this keeps memory visible across API and
  workflow-worker replicas without process-local synchronization.
- Production `AgentSwarmRun` and `AgentWorkerAssignment` facts follow the same
  rule: `SQLAlchemyAgentSwarmState` persists and reloads them through
  `ConversationRepository`. They are not mirrored into `ApplicationStore` or
  loaded into compatibility runtime state.
- Production `ToolInvocation` and append-only `AuditEvent` facts are also
  repository-only. `SQLAlchemyToolInvocationApplicationState`,
  `SQLAlchemyToolInvocationRuntimeState`, and `SQLAlchemyAuditEventPersistence`
  provide their command/query boundaries; startup hydration must not recreate
  process-local invocation or audit maps.
  Agent memory context views must obtain AgentGoal
  state through `AgentGoalLifecycleApplicationService`, not direct
  `ApplicationStore.agent_goals` reads. Conversation summary checkpoint selection and
  construction must be delegated to `ConversationSummaryCheckpointService`, and
  automatic checkpoint writes must be delegated to
  `ConversationSummaryCheckpointApplicationService`, not store private helpers.
  Memory checkpoint events must be published through
  `PlatformEventApplicationService`, not `ApplicationStore._push_event`.
  System-image memory context sections and long-term system-image refs must be
  delegated to `SystemImageMemoryContextApplicationService`; Agent memory must
  not directly read `baselines`, `raw_assets`, `knowledge_objects`,
  `context_relationships`, or `quality_metric_snapshots`.
  Agent memory receives retrieval hits and trace refs from the asynchronous
  `SystemImageRetriever` result contract. Concrete retrievers own retrieval
  evidence persistence; Agent memory must not create `RetrievalRun` records,
  append `retrieval_runs`, or calculate system-image baseline, embedding,
  rerank, or fallback metadata inline.
- `domain/agent/name_extraction.py`: pure Agent naming extraction policy for
  deriving project and version names from English or Chinese user text. Legacy
  `ApplicationStore` methods may provide fallback counters while delegating to
  this policy, but must not own language-specific regular expressions or
  fallback naming rules inline.
- `application/agent/orchestrator.py`: deterministic Conversation Orchestrator
  for mapping natural language and current space context into clarification,
  direct-answer, ToolInvocationPlan, or AgentGoalProposal decisions. The
  app-root `conversation_orchestrator.py` module is a compatibility alias only;
  planners and message services must import this from the agent application
  package.
- `application/agent/AgentReplyApplicationService`: agent LLM reply generation
  and assistant-message persistence. Query/read-model services may call this
  application boundary but must not use `ApplicationStore` as a LLM reply
  facade or append conversation messages directly. The service receives only
  `AgentReplyMemoryPort`, `AgentReplyGenerationPort`,
  `AgentReplyModelSettingsPort`, and `AgentReplyMessageWriterPort`; it must not
  import, retain, or dynamically inspect `ApplicationStore`. The composition
  root injects `AgentMemoryManager`, the LLM gateway,
  `ModelConfigurationApplicationService`, and the canonical conversation
  message writer through these contracts. `ApplicationStore` must not
  expose `_generate_llm_content`, `_conversation_system_prompt`, or
  `_conversation_context_snapshot`. Chat provider secrets and active model
  selections must be read through `ModelConfigurationApplicationService`, not
  through private `ApplicationStore` model-configuration facades.
- `application/agent/plans.py`: AgentGoal proposal-to-tool-plan compilation,
  including state-aware system-image follow-up planning and tool catalog
  validation. The app-root `agent_goal_plan_compiler.py` module is a
  compatibility alias only; graph runtimes must import the compiler from the
  application package.
- `application/agent/planner.py`: deterministic and LLM-structured
  conversation-to-agent-decision planning. The app-root `agent_planner.py`
  module is a compatibility alias only; store initialization and message
  orchestration must import planners from the application package.
- `infrastructure/workflow/agent_workflow_factory.py`: Agent workflow runtime
  selection from deployment environment and Temporal gateway assembly. Temporal
  goal-state sinks may write returned workflow facts only through
  `AgentGoalProjectionApplicationService`; they must not duplicate
  conversation projection rules or call store private projection helpers. The
  app-root `agent_workflow_runtime.py` module is a compatibility alias only.
  User-initiated workflow start and resume payloads must carry the authenticated
  actor snapshot. Temporal activities run outside the HTTP request process and
  must restore that actor scope before invoking the Agent loop or any governed
  tool; falling back to a process-default user is forbidden.
- `infrastructure/workflow/agent_graph_factory.py`: Agent graph runtime
  selection from deployment environment and LangGraph gateway assembly. The
  app-root `agent_graph_runtime.py` module is a compatibility alias only and
  must not regain graph implementation, environment branching, or gateway
  construction.
- `application/agent/swarm.py`: bounded sub-agent assignment orchestration,
  source-specific candidate merge tracking, and swarm persistence. Swarm event
  publication must go through `PlatformEventApplicationService`, not
  `ApplicationStore._push_event`. The app-root `agent_swarm.py` module is a
  compatibility alias only; system-image tool handlers must request swarm
  startup through `AgentApplicationService`, not by reaching into the store.
- `infrastructure/system_image/source_ingestion.py`: source ingestion adapter
  for local files and external source references. It owns filesystem reads,
  URI-scheme allowlisting, source byte/file limits, content fingerprints, and
  raw text-unit extraction. Application code must import it from
  `infrastructure.system_image`, not from the app-root compatibility module.
- `application/system_image/context_extraction.py`: store-model-backed
  context extraction use case for turning indexed code, US documents, and test
  assets into knowledge objects, context relationships, and quality metric
  snapshots. It may use deterministic parsing heuristics during migration, but
  it must stay under the system-image application package instead of app-root.
- `domain/agent/runtime_models.py`: pure Agent planning value objects for
  `AgentGoalProposal`, `ToolPlanStep`, `ToolInvocationPlan`, and
  `OrchestratorDecision`. Orchestrators, planners, workflow gateways, and graph
  runtimes must import these models from the domain package; the app-root
  `agent_runtime_models.py` module is a compatibility alias only.
- `domain/agent/state_machine.py`: pure AgentGoal and AgentStep lifecycle
  state machine for checkpoints, phases, pauses, failures, and completion. It
  must describe its inputs with protocols and must not import `models.py`;
  `agent_goal_state_machine.py` at the app root is a compatibility alias only.
- `domain/agent/memory.py`: pure Agent memory context value object and stable
  context hash/summary functions. Runtime code must import
  `AgentMemoryContext`, `memory_context_hash`, and `memory_context_summary`
  from the domain package.
- `application/agent/memory.py`: store-backed Agent memory context assembly,
  system-image memory retrieval, retrieval tracing, and persistence
  coordination. The root `agent_memory.py` module is a compatibility alias
  only; it must not regain `AgentMemoryManager` implementation or direct
  `ApplicationStore` access.
- `application/system_image/SystemImageApplicationService`: system-image read
  and write use cases, including source registration, ingestion, context
  materialization, baseline initialization, knowledge reads, and system image
  snapshot reads. `SystemImageToolHandler` is only an adapter: system-image
  mutations live in this service, runtime status goes through
  `ToolInvocationApplicationService`, assistant messages go through
  `AgentReplyApplicationService`, and Agent swarm startup goes through
  `AgentApplicationService`. `ApplicationStore.list_knowledge_objects`,
  `get_knowledge_object`, and `get_system_image` are compatibility delegates
  only and must not reintroduce inline system-image read aggregation. During
  the compatibility phase, `ApplicationStore` must hold a constructor-injected
  `system_image_app` instance and delegate to it directly; it must not expose
  `_system_image_app` factories or create this service inside read methods.
- `application/system_image/SystemImageKnowledgeQueryApplicationService`:
  knowledge-object read-model query service. It owns project read-model refresh
  before knowledge reads and the temporary store-backed knowledge object lookup.
  `SystemImageApplicationService` should delegate list/detail knowledge reads
  to this query service instead of reading `knowledge_objects` directly.
- `application/system_image/SystemImageSnapshotQueryApplicationService`:
  system-image snapshot read query service. It owns the temporary store-backed
  `system_image_service.get` delegation. `SystemImageApplicationService` should
  delegate snapshot reads here instead of calling lifecycle services inline.
- `application/system_image/SystemImageMemoryContextApplicationService`:
  Agent-readable system-image memory query service. It owns the temporary
  store-backed assembly of system-image sections and long-term project refs for
  Agent memory. Agent services should consume this boundary instead of reading
  baselines, raw assets, knowledge objects, context relationships, or metric
  snapshots directly.
- `application/system_image/SystemImageRetrievalTraceApplicationService`:
  compatibility trace service for older deterministic retrieval callers. New
  Agent retrieval uses the asynchronous `SystemImageRetriever` contract and
  receives persisted trace refs in `SystemImageMemorySearchResult`.
- `application/system_image/SystemImageLifecycleApplicationService`:
  context materialization and Official System Image baseline lifecycle service.
  It owns materialization and baseline initialization delegation while the
  deeper `SystemImageService` remains store-backed. `SystemImageApplicationService`
  should delegate these lifecycle use cases here.
- `application/system_image/SystemImageSourceBindingApplicationService`:
  source-binding and ingestion entry-point service. It owns project existence
  checks, source spec normalization, missing-source checks, source registration,
  and ingestion delegation while the deeper `SystemImageService` is still
  store-backed. `SystemImageApplicationService` should delegate these source
  use cases to this service instead of calling `system_image_service` directly.
- `application/system_image/raw_asset_chunks.py`: raw asset chunk
  materialization application component. It owns converting indexed source text
  units into `RawAssetChunk` records, storing chunk payloads, and reading chunk
  text back for downstream embedding. `SystemImageService` should call this
  component instead of implementing chunk loops inline.
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
- `domain/system_image/materialization.py`: source-evidence readiness policy.
  Official materialization must contain source-backed context objects,
  relationships, and a code-quality metric. Synthetic fixture or fallback
  evidence is rejected. Demo content is created only through the explicitly
  local `application/platform/demo_seed.py` path and never by
  `SystemImageService`.
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
- `application/system_image/service.py`: store-backed system-image lifecycle
  coordinator for state initialization, source use-case delegation,
  context materialization, baseline state, quality context, and persistence
  coordination. It may coordinate object storage and current repositories
  during migration, but pure rules and write loops must stay in
  `domain/system_image` or focused application components. The
  app-root `system_image_service.py` module is a compatibility alias only.
  Embedding/rerank provider secrets and active model selections must be read
  through `ModelConfigurationApplicationService`; system-image code must not
  call private `ApplicationStore` model-configuration facades directly.
  The composition root injects its public settings and API-key providers into
  `DurableSystemImageWorkspaceAdapters`; the workspace must not construct the
  model configuration service itself. It also receives the production-like runtime
  policy through composition. In production-like profiles, any non-live
  embedding or rerank result raises
  `SystemImageModelRouteUnavailableError`; mock hash vectors and rule-based
  rerank output are development-only and must never be persisted as an
  Official System Image fact.
- `application/system_image/materialization_snapshot.py`: transaction snapshot
  for context materialization. Source ingestion remains an independently
  durable fact, while extracted objects, relationships, metrics, US work
  items, embeddings, retrieval/rerank records, task contexts, and quality
  profiles are restored together when provider or persistence work fails.
- `application/system_image/system_image_models.py`: canonical system-image
  application contract DTOs for raw assets/chunks, knowledge objects,
  baselines, context relationships/overlays, quality metric snapshots,
  embedding/retrieval/rerank records, task contexts, quality profiles, build
  state, and system image snapshots. During migration, root `models.py` may
  re-export these names for API compatibility, but it must not define them.
  System-image services, ingestion adapters, repositories, Agent memory/swarm,
  quality-loop context updates, governance, and `ApplicationStore` must import
  these DTOs from this module.
- `application/platform/project_models.py`: canonical project and version read
  model DTOs (`ProjectCard`, `VersionSummary`). Root `models.py` may re-export
  them during migration, but persistence, project routes, workspace services,
  and system-image response contracts must import them from this platform
  application contract.
- `application/system_image/retrieval.py`: Agent-facing asynchronous
  system-image retrieval port and result contract. Production binds it to the
  PostgreSQL FTS/pgvector and rerank implementation; the in-process lexical
  adapter remains test/migration-only. The root `system_image_retriever.py`
  module is a compatibility alias only.
- `domain/system_image/source_binding.py`: pure source-binding policy for the
  required code source, optional US/test sources, placeholder URIs, missing-source detection, and
  ingestion readiness. `SystemImageService` may supply current project/sources
  to this policy, but it must not duplicate required-source branching rules.
- `domain/system_image/build_state.py`: pure Official System Image build-state
  policy for failure precedence, missing source requirements, ingesting/indexed
  progression, materialized-but-not-promoted status, and ready status.
  `SystemImageService` may provide current source statuses, baseline status,
  context flags, and project status, but it must not own these state transition
  labels or recommended-tool rules inline.
- `domain/system_image/chunking.py`: pure raw-asset chunking policy for text
  normalization, chunk splitting, content hashes, deterministic chunk IDs,
  source-type-to-chunk-kind mapping, token estimation, and stable hashes.
  `SystemImageService` may coordinate object storage and persistence, but it
  must not reimplement chunk identity or chunk classification rules inline.
- `domain/system_image/quality_context.py`: pure quality-context policy for
  missing quality context detection, deterministic context hashes, confidence,
  risk, coverage, automation feasibility, release scoring, and risk-driver
  explanations. `SystemImageService` may pass current project counters and
  materialized metrics to this policy, but it must not own these scoring
  formulas inline.
- `domain/system_image/us_work_items.py`: pure policy for deriving US work
  items from system-image knowledge objects and for assigning default quality
  asset lanes. `SystemImageUSWorkItemApplicationService` may map these
  decisions into current API DTOs and persist them, but service coordinators
  must not own US-object selection, US code extraction, default
  owner/status/risk/progress, or lane templates inline.
- `application/quality_loop/project_versions.py`: project setup, version
  setup, version input import, participant assignment, risk initialization, and
  US task-start write use cases live in `ProjectVersionApplicationService`.
  `ProjectVersionToolHandler` is only an adapter: it calls this service for
  mutations, `ToolInvocationApplicationService` for runtime status, and
  `AgentReplyApplicationService` for assistant progress messages. Project and
  version record creation defaults and release-readiness seed records belong in
  this service. Persistence, access grants, conversation initialization, and
  system-image draft effects remain behind `ProjectVersionWorkspacePort`.
  During the compatibility phase, `ApplicationStore` holds the assembled
  `project_versions` instance and delegates project/version creation to it
  directly; it must not instantiate this service inside `create_project` or
  `create_version`.
  `ApplicationStore.create_project` and `ApplicationStore.create_version` are
  compatibility delegates only and must not reintroduce inline project/version
  assembly. `application/quality_loop/use_cases.py` is reserved for
  `QualityLoopApplicationService`; do not add project/version setup,
  participant, risk, US import, or US task-start mutation logic there.
- `application/quality_loop/QualityLoopApplicationService`: compatibility
  facade for quality-loop write use cases. It may coordinate asset-pack
  refresh, run start, failure/healing, release advice, and expose legacy method
  names for tool handlers, but it must delegate quality-step completion to
  `QualityStepCompletionApplicationService`, automation runner execution to
  `QualityRunExecutionApplicationService`, and concrete fact mutations to the
  owning application services below. All collaborators are assembled by the
  composition root and injected explicitly; this application service must not
  retain `ApplicationStore`, discover services through Store attributes, or
  construct subordinate application services.
- `application/quality_loop/QualityStepCompletionApplicationService`: write
  boundary for scope/scenario/case, automation, and release quality-step
  completion. It consumes pure plans from
  `domain/quality_loop/quality_step_plan.py`, invokes runner-backed automation
  through `QualityRunExecutionApplicationService`, creates failure reports when
  automation fails, records metric overlays through
  `QualityImageUpdateApplicationService`, writes asset parts through
  `QualityAssetPackApplicationService`, and persists lane/US progress through
  `QualityAssetProgressApplicationService`. Do not add quality-step plan
  execution logic back to `application/quality_loop/use_cases.py`. Historical
  asset context must be read through `QualityAssetPackApplicationService`,
  never through Store projections.
- `application/quality_loop/QualityRunExecutionApplicationService`: write-side
  run execution boundary for quality-loop automation. It consumes
  `QualityAutomationExecutionPort`, `QualityAssetPackReadPort`, and
  `QualityExecutionEvidenceReadPort`; validates the approved automation
  blueprint before dispatch, maps returned execution evidence into canonical
  `execution_evidence` refs, and exposes durable evidence lookup for release
  planning. PostgreSQL-backed pack/evidence reads and runner lifecycle effects
  remain infrastructure concerns. This service must not depend on
  `ApplicationStore`, call `ApplicationStore.run_orchestrator`, or read
  compatibility projections directly.
- `application/quality_loop/QualityLoopVersionContextApplicationService`:
  active-version boundary for quality-loop writes. It owns active version
  resolution and creation of the default `Initial Quality Loop` version when a
  quality step needs version context. Main quality-loop use cases may pass this
  provider to pack, release, and system-image metric services, but they must
  not read `versions` or create default versions inline.
- `application/quality_loop/QualityAssetPackApplicationService`: write-side
  boundary for `QualityAssetPack` facts. It owns pack initialization/refresh,
  asset part upsert, part revisioning, pack status/current revision/evidence
  aggregation, source-reference resolution, and persistence through
  `QualityAssetPackWorkspacePort`.
  `QualityStepCompletionApplicationService` may decide which quality-step part
  should be written, but it must delegate pack mutation here instead of
  directly building `QualityAssetPart` or calling `upsert_quality_asset_pack`.
  Production persistence belongs to
  `infrastructure/quality_loop/SQLAlchemyQualityAssetPackWorkspace` and reads
  and writes durable PostgreSQL facts. `LegacyQualityAssetPackWorkspace` is
  test/migration-only and must not be selected by production composition.
- `application/quality_loop/QualityAssetProgressApplicationService`: write-side
  progress boundary for quality asset lanes and US board progress. It
  materializes default asset lanes, updates lane status/summary, and persists
  US progress/status/next-action changes through
  `QualityAssetProgressWorkspacePort`. `QualityStepCompletionApplicationService`
  coordinates quality-step plans but must delegate lane and US progress
  persistence here instead of reintroducing inline `asset_lanes` or `us_items`
  write rules. Production composition uses
  `infrastructure/quality_loop/SQLAlchemyQualityAssetProgressWorkspace` with
  lane- and US-scoped writes. `LegacyQualityAssetProgressWorkspace` remains
  test/migration-only.
- `application/quality_loop/QualityFailureReportApplicationService`:
  write-side boundary for failure analysis facts and failed-run healing state.
  It reads evidence through `QualityExecutionEvidenceReadPort`, materializes
  missing evidence through `QualityAutomationExecutionPort`, delegates failure
  identity and report decisions to
  `domain/quality_loop/failure_analysis.py`, then persists the updated `Run`
  and affected `FailureReport` facts through `QualityFailureWorkspacePort`.
  `SQLAlchemyQualityFailureWorkspace` must commit the target run and reports in
  one transaction without deleting peer facts created by concurrent workers.
  The service must not retain
  `ApplicationStore` or call repositories directly. `QualityLoopApplicationService`
  may decide when failure analysis or healing is required, but it must not
  directly call `identify_failure`, `decide_failure_report`,
  `replace_failure_reports`, or run persistence helpers.
- `application/quality_loop/QualityReleaseReadinessApplicationService`:
  write-side boundary for `ReleaseReadiness` facts and project release-risk
  synchronization. It gathers open `FailureReport` facts, delegates scoring to
  `domain/quality_loop/release_readiness.py`, persists `ReleaseReadiness`, and
  updates project progress/blocker/risk fields. `QualityLoopApplicationService`
  may request release advice or release assessment, but it must not directly
  call `decide_release_readiness`, `upsert_release_readiness`, or mutate
  project release-risk fields.
- `application/quality_loop/QualityImageUpdateApplicationService`: write-side
  boundary for quality-loop updates that materialize into the system image. It
  creates `QualityMetricSnapshot` facts, creates `ContextObjectOverlay`
  records, updates baseline metric counters, ensures a baseline exists, and
  persists the system-image read model through the least-privilege
  `QualityImageWorkspacePort`. `QualityStepCompletionApplicationService`
  may decide which metrics were produced by a quality step, but it must not
  directly construct system-image DTOs or call system-image repositories.
  This service must not retain `ApplicationStore` or mutate compatibility
  dictionaries.
- `application/quality_loop/QualityLoopContextQueryApplicationService`: current
  quality-loop context query boundary for write-side use cases. It resolves the
  current `TaskContext`, `QualityProfile`, `QualityAssetPack`, and planner-facing
  quality state through `QualityLoopContextWorkspacePort`. Agent,
  project/version, and quality-loop application services must depend on this
  service instead of reading compatibility caches, calling repositories,
  reintroducing `ApplicationStore._current_*` private helpers, or using platform
  BFF read models. Production context reads are implemented by
  `infrastructure/quality_loop/SQLAlchemyQualityLoopContextWorkspace` against
  durable repositories. `LegacyQualityLoopContextWorkspace` remains
  test/migration-only.
- `application/quality_loop/QualityLoopScopeQueryApplicationService`:
  ToolInvocation scope query boundary for quality-loop actions. It resolves
  project, US, failed-run scope, and route query keys from invocation payloads,
  conversation scope, run summaries, execution evidence, and US ownership
  through `QualityLoopScopeWorkspacePort`. Explicit project/US/run identifiers
  must be mutually owned; unknown or cross-project combinations fail closed
  before a write-side use case can execute. Production scope resolution is
  implemented by
  `infrastructure/quality_loop/SQLAlchemyQualityLoopScopeWorkspace` and reads
  conversation, US, run, and execution-evidence ownership from durable
  repositories rather than process-local projections.
  `QualityLoopApplicationService` may expose compatibility methods, but the
  actual scope inference rules must live in this service instead of inline
  write-side use-case methods or direct `ApplicationStore` reads.
- `application/quality_loop/QualityLoopReleaseDecisionQueryApplicationService`:
  release decision query boundary for governance use cases. Platform governance
  may submit approvals and promote baselines, but it must read current
  `ReleaseDecision` facts through this quality-loop service and
  `QualityLoopReleaseDecisionReadPort` instead of calling or reintroducing
  `ApplicationStore._current_release_decision`, reading compatibility
  projections, or using platform workspace read models. The production port is
  implemented by `QualityLoopRepository` and selects the latest durable
  PostgreSQL fact deterministically.
- `application/quality_loop/quality_models.py`: canonical quality-loop
  application contract DTOs for US work items, asset lanes, quality asset
  packs/parts, run summaries/details, execution evidence, failure reports,
  approval details, release decisions/readiness, and `QualityLoopState`.
  During migration, root `models.py` may re-export these names for API
  compatibility, but it must not define them. Quality-loop use cases, runner
  adapters, governance services, persistence repositories, and the temporary
  `ApplicationStore` facade should import these DTOs from this module.
- `infrastructure/runner/RunOrchestrator`: execution-run adapter boundary for
  generated automation. Task-context lookup is injected through
  `RunTaskContextProvider`, run/evidence persistence through
  `QualityRunWorkspacePort`, and binary artifact writes through
  `EvidenceObjectStoragePort`. Production persistence is implemented by
  `infrastructure/quality_loop/SQLAlchemyQualityRunWorkspace`, using
  entity-grained run upserts and run-scoped evidence replacement so concurrent
  runs cannot overwrite each other. MinIO/S3 details live only in the injected
  object-storage adapter. `RunOrchestrator` must not
  retain `ApplicationStore`, mutate compatibility dictionaries, call
  repositories, or reach through the Store to object storage.
- `domain/quality_loop/release_readiness.py`: pure release-readiness decision
  policy for blocked-vs-ready status, release score, blocker count, approval
  count for human fallback, execution health text, release summary, blocker item
  formatting, and project progress floor. Application services may collect open
  failures and persist `ReleaseReadiness`, but they must not own these scoring
  or status rules inline. Release-readiness writes and project release-risk
  synchronization belong in `QualityReleaseReadinessApplicationService`, not
  the main quality-loop use case.
- `domain/quality_loop/release_decision.py`: pure release-decision policy for
  status selection (`ready`, `conditional`, `blocked`, `needs_evidence`),
  stable decision IDs, rationale text, and evidence reference composition.
  Governance application services may collect readiness and execution evidence
  and persist `ReleaseDecision`, but they must not own these release-decision
  rules inline.
- `domain/quality_loop/quality_assets.py`: pure quality-asset policy for
  default asset-lane templates, lane identity compatibility, quality asset part
  revision increments, QualityAssetPack status transitions, current revision,
  and evidence aggregation. Application services may create API DTOs and
  persist packs/lanes, but they must not duplicate lane templates or pack status
  rules inline. Pack persistence belongs in
  `QualityAssetPackApplicationService`, and lane/US progress persistence
  belongs in `QualityAssetProgressApplicationService`, not the main
  quality-loop use case.
- `domain/quality_loop/quality_step_plan.py`: pure quality-step plan policy
  for scope/scenario/case generation, automation outcome handling, and
  post-readiness release assessment, including lane updates, US
  progress/status/next-action transitions, quality metric specs,
  QualityAssetPart specs, object/evidence refs, summary text, failure-report
  requirements, and next-tool sequencing. Application services may execute
  these plans by calling persistence helpers and may invoke runners, create
  `FailureReport`, and collect release evidence refs, but quality-step rule
  tables must not live inline in `QualityStepCompletionApplicationService`.
  Quality metric materialization into system-image snapshots and overlays
  belongs in `QualityImageUpdateApplicationService`, not the main quality-loop
  use case.
- `domain/quality_loop/failure_analysis.py`: pure failure-analysis and bounded
  healing policy for stable failure identity/fingerprint generation,
  failure-kind classification, healing attempt counts, fallback-to-human
  decisions, run healing status, and root-cause text. Application services may
  collect runner evidence, find existing reports, create DTOs, and persist run
  updates, but they must not own these failure decision rules inline.
  Failure-report writes and run healing synchronization belong in
  `QualityFailureReportApplicationService`, not the main quality-loop use case.
- `domain/quality_loop/failure_loop_progress.py`: pure failed-run loop progress
  policy for analysis/healing/fallback summary text, next-tool selection,
  assistant progress copy, planner kind, and fallback-to-human flags.
  Application services may resolve failed-run scope, persist `FailureReport`,
  and attach run/report object refs, but they must not own failure-loop progress
  branching or copy inline.
- `domain/quality_loop/step_guidance.py`: pure quality-loop step guidance
  policy for runtime progress summaries, assistant follow-up copy, and fallback
  guidance. Application services and tool handlers may request guidance for a
  step, but they must not own or duplicate step-to-copy maps inline.
- `domain/quality_loop/version_participants.py`: pure version participant
  assignment policy for assignment-payload normalization, explicit/default/
  existing owner precedence, Unassigned fallback, and assigned-count decisions.
  Project/version application services may map these decisions into `USItem`
  updates and persist them, but they must not own assignment shape parsing or
  owner fallback rules inline.
- `domain/quality_loop/version_risk.py`: pure version-risk initialization
  policy for US risk bucketing, default next-action fallback, aggregate project
  risk, project progress floor, and initialization summary text. Project/version
  application services may persist updated US items and project/version facts,
  but they must not own these thresholds or summary rules inline.
- `domain/quality_loop/version_us_import.py`: pure version US input-import
  policy for supported payload keys, raw item normalization, generated-ID
  injection, default US attributes, merge rules, progress monotonicity, imported
  item decisions, and ordered US board decisions. Project/version application
  services may supply an ID factory, map decisions into API DTOs, and persist
  them, but they must not own raw payload parsing or import merge rules inline.
- `domain/quality_loop/us_task_start.py`: pure US task-start policy for
  requested-or-first target selection, analysis status transition, progress
  floor, next-action copy, assistant summary text, context-sensitive next tools,
  and follow-up decisions. Project/version application services may persist
  updated US items, materialize task context, and attach context/profile object
  refs, but task-start rules and response copy must live in this domain policy.
- `application/platform/GovernanceApplicationService`: approval request/decision,
  structured merge resolution, release decision submission, and baseline
  promotion write use cases. `GovernanceToolHandler` must stay a tool-runtime
  adapter and must not directly mutate approval, release, or baseline facts.
- `application/platform/QueryToolApplicationService`: tool-native read-model
  planning, fallback summary selection, LLM answer generation, assistant message
  persistence, and read ToolResult construction. `QueryToolHandler` must stay a
  runtime adapter and must not assemble project/version/workspace summaries
  directly. Cross-domain facts enter through `AgentQueryReadPort`; transitional
  in-process maps are exposed only by
  `infrastructure/platform/CompatibilityPlatformQueryReadModel`.
- `domain/platform/rbac.py`: pure tool RBAC policy for role normalization,
  aliases, role ordering, query/analysis/execution/project/governance/critical
  required-role thresholds, and authorization denial summaries.
  `ToolInvocationRuntime` may call this policy but must not own these role
  rules inline. App-root `rbac.py` is a compatibility alias only.
- `domain/platform/tool_governance.py`: pure tool governance-gate policy for
  confirmation phrase detection, user-confirm gates, approval-required gates,
  approval verifier results, and gate decision summaries.
  `ToolInvocationRuntime` may call this policy but must not own these gate
  rules inline. App-root `tool_governance.py` is a compatibility alias only.
- `application/platform/ToolApprovalVerifierApplicationService`: application
  verifier for approval-required tool invocations. It resolves project context
  from invocation payload or conversation scope, checks that the approval belongs
  to the project, and validates approved/accepted/completed status. It depends
  only on `ToolApprovalVerificationStatePort`. Production composition binds the
  port to `infrastructure/platform/SQLAlchemyToolApprovalVerificationState`,
  which reads committed conversation scope and project approval status from
  PostgreSQL. `ProjectedToolApprovalVerificationState` is test/migration-only.
  The domain
  `ToolGovernance` policy may call this verifier through its protocol callback,
  but neither the verifier nor its port may retain `ApplicationStore` or scan
  Store projections directly.
- `application/platform/ModelConfigurationApplicationService`: settings reads
  and updates, provider connection tests, multi-instance model configuration,
  test-token validation, payload fingerprinting, active route selection, and
  legacy model import. It depends only on the state, repository, secret,
  provider-gateway, and test-grant contracts in
  `application/platform/model_configuration_ports.py`; it must not retain
  `ApplicationStore` or import PostgreSQL, OpenSSL, or concrete LLM adapters.
  Production binds `ModelConfigurationStatePort` to
  `infrastructure/platform/SQLAlchemyModelConfigurationState`. It reloads base
  preferences and legacy migration secret metadata from PostgreSQL for every
  request so route activation performed by another API replica is immediately
  visible. `ProjectedModelConfigurationState` is test/migration-only; it must
  never be the production source of settings facts. Repository, encryption, and
  provider implementations remain infrastructure concerns. Legacy
  `ApplicationStore` model-setting methods are compatibility delegates only.
- `application/platform/model_config_test_grants.py` defines the durable
  one-time grant port used after a successful provider test.
  `infrastructure/persistence/model_config_test_grant_repository.py` stores
  only SHA-256 token digests and consumes a matching, unexpired grant with one
  atomic delete. Raw test tokens must never be persisted or kept in
  `ApplicationStore` process memory.
- `application/platform/model_settings.py`: platform model-provider and studio
  settings contract types for chat, embedding, and rerank routes. App-root
  `models.py` may re-export these names for compatibility, but new platform,
  LLM, persistence, and HTTP code must import them from this application-layer
  contract instead of adding more settings DTOs to the global model bucket.
- `application/platform/ToolInvocationApplicationService`: tool catalog reads,
  ToolInvocation create/confirm/execute/gate application entry points,
  invocation filtering, runtime status emission, invocation update SSE emission,
  and audit-event query use cases. It receives
  `ToolInvocationApplicationStatePort`, `ToolInvocationExecutionPort`,
  `ToolInvocationAccessPort`, and `ToolStatusEventPort`; it must not import,
  retain, or construct `ApplicationStore`. The production projection adapter is
  `infrastructure/platform/tool_invocation_state.py`. Tool handlers and the
  lifecycle runtime emit status through `ToolStatusEventPort`, implemented by
  `PlatformEventApplicationService`, rather than depending on this concrete
  application service or calling Store event helpers. During migration,
  `ApplicationStore` may hold the composed `tool_invocations_app` delegate but
  must not expose `_tool_invocation_app` factory helpers.
- `application/platform/ToolInvocationProjectionApplicationService`: the
  single platform writer for persisting `ToolInvocation` facts used by
  conversation read models. It depends only on
  `ToolInvocationProjectionStatePort`. Production composition uses
  `infrastructure/platform/SQLAlchemyToolInvocationProjectionState`, which
  writes the shared ToolInvocation relation directly. `ConversationRepository`
  assembles `ConversationSession.tool_invocations` from those committed rows,
  so production must not mirror invocations in a Python dictionary or rewrite
  the Conversation aggregate after every status change.
  `ProjectedToolInvocationProjectionState` remains compatibility/test-only and
  uses explicit facts and persistence callbacks. `ToolInvocationRuntime`,
  `PlatformEventApplicationService`, and compatibility store methods must call
  this service instead of duplicating conversation projection rules or calling
  `ApplicationStore._upsert_invocation_in_conversation` directly. Neither the
  application service nor its port may import or retain `ApplicationStore`.
  `ApplicationStore._upsert_invocation_in_conversation` is a compatibility
  delegate only. During the compatibility phase, `ApplicationStore` must hold a
  constructor-injected `tool_projection` instance and delegate to it directly;
  it must not instantiate this service inside projection methods.
- `application/platform/PlatformAuditApplicationService`: platform audit write
  use cases. It owns generic audit persistence and AgentGoal audit-event
  payload construction and depends only on `AuditEventPersistencePort`.
  Production writes append-only facts directly through
  `infrastructure/platform/SQLAlchemyAuditEventPersistence` and reads them from
  the shared repository. `ProjectedAuditEventPersistence` is test/migration-only
  and must not provide production query facts. The application service must not
  import or retain `ApplicationStore`. Legacy
  `ApplicationStore.record_audit_event` and
  `ApplicationStore.record_agent_goal_audit_event` are compatibility delegates
  only and must not construct `AuditEvent` payloads inline. During migration,
  `ApplicationStore` may hold an injected `platform_audit` instance, but it must
  not expose `_audit_app` factory helpers.
- `application/platform/PlatformEventApplicationService`: platform SSE/outbox
  event publication use cases. It owns `EventPayload` construction,
  entity-version increments, tool-status event emission, and swarm snapshot
  event construction. Queue creation, fan-out, and stream iteration must go
  through `PlatformEventStreamApplicationService`. Tool status fact persistence
  and conversation projection must go through
  `ToolInvocationProjectionApplicationService`. AgentGoal, ToolInvocation, and
  AgentSwarm snapshot payload reads enter through
  `PlatformEventEntityReaderPort`; tool status projection enters through
  `ToolInvocationEventProjectionPort`. The application service must not import
  or retain `ApplicationStore`, inspect compatibility dictionaries, or
  construct concrete event, projection, or repository services.
  `ApplicationStore` must not
  expose `_push_event`, `_push_goal_event`, `_event_payload`,
  `_emit_tool_status`, or `_emit_simple_answer`. Legacy stream methods
  `ApplicationStore.stream_events`, `ApplicationStore.stream_goal_events`,
  `ApplicationStore.stream_swarm_events`, and
  `ApplicationStore._swarm_snapshot_event` are compatibility delegates only
  until routers consume `PlatformEventStreamApplicationService` directly. During
  migration, `ApplicationStore` may hold an injected `platform_events` instance,
  but it must not expose `_event_app` factory helpers.
- `application/platform/PlatformEventStreamApplicationService`: durable event
  stream boundary for conversation, AgentGoal, and swarm streams. It persists
  through `EventOutboxPort` before fan-out and accesses process-local wake-up
  queues only through `EventStreamBufferPort`. It supports replay by
  `Last-Event-ID`, polls PostgreSQL for multi-instance delivery, and emits SSE
  heartbeats. `SSEWakeUpBuffer` process-local queues are wake-up signals only;
  PostgreSQL outbox order and replay remain authoritative. Poll and heartbeat
  settings are injected by `infrastructure/platform/event_runtime.py`; the
  application service must not read environment variables or retain
  `ApplicationStore`.
  `PlatformEventApplicationService` and compatibility store methods must call
  this service directly; `ApplicationStore` must not expose
  `_get_or_create_event_queue`, `_get_or_create_goal_queue`, or
  `_get_or_create_swarm_queue` helpers.
- `application/platform/event_ports.py`: application-owned contracts for the
  durable event log, process-local wake-up buffer, event stream publication and
  replay, entity reads, and ToolInvocation projection. Infrastructure
  implementations may depend on these contracts; the application layer must
  not import SQLAlchemy, concrete repositories, environment configuration, or
  compatibility Store state.
- `infrastructure/persistence/EventOutboxRepository`: PostgreSQL outbox adapter
  that assigns monotonic event versions and supports ordered stream replay.
- `interface/sse`: HTTP transport adapter that serializes event IDs, event
  names, compact payloads, heartbeats, and no-buffer response headers.
- `application/platform/tool_models.py`: platform tool-command contract types
  for `ToolDefinition`, `ToolInvocation`, `ToolResult`,
  `ToolInvocationRequest`, `AuditEvent`, and `EventPayload`. App-root
  `models.py` may re-export these names during migration, but tool runtime,
  tool handlers, Tool Catalog, persistence adapters, Agent graph/message
  orchestration, and HTTP platform routes must import them from this
  application-layer contract.
- `application/platform/tool_catalog.py`: platform-owned Tool Catalog
  definitions. It is the preferred home for first-party `ToolDefinition`
  declarations across project/version, quality-loop, governance, query, and
  system-image tools. `ApplicationStore` may combine catalog groups during
  migration, but must not define `ToolDefinition(...)` inline. App-root
  `system_image_tool_catalog.py` is a compatibility alias only; new tool
  catalog entries should be added under `application/platform` or split into a
  platform-owned catalog package.
- `application/platform/runtime.py`: canonical ToolInvocation lifecycle runtime
  for every business tool action. It owns idempotent invocation creation,
  canonical tool aliases, RBAC invocation, confirmation/approval gate dispatch,
  handler dispatch, and audit persistence. The app-root
  `tool_invocation_runtime.py` module is a compatibility alias only; store
  initialization must import `ToolInvocationRuntime` from this application
  package.
- Production ToolInvocation command state is PostgreSQL-backed through
  `SQLAlchemyToolInvocationRuntimeState` and `ConversationRepository`.
  `idempotency_scope + tool_id + idempotency_key` is protected by a database
  unique constraint, payload reuse is verified with a canonical fingerprint,
  and `pending`/`waiting_confirmation` execution is claimed under a row lock
  before a handler runs. `ProjectedToolInvocationRuntimeState` is restricted to
  isolated tests and migration compatibility; it must not be selected by
  production composition. SSE entity reads must use committed invocation facts
  rather than `ApplicationStore.tool_invocations`.
- Legacy `ApplicationStore` tool/audit methods are compatibility delegates only
  and must not regain tool filtering, canonical tool id handling, created-at
  derivation, audit filtering, audit payload construction, or direct runtime
  calls.
- `application/platform/tool_handlers/`: platform-owned ToolInvocation adapter
  package. It contains the registration-only `ToolInvocationHandlerRegistry`
  plus thin adapters for system-image, project/version, quality-loop,
  governance, and query tools. These adapters accept domain application
  services plus `ToolStatusEventPort`, never the concrete
  `ToolInvocationApplicationService`; they must not import, type-check, or
  construct `ApplicationStore` directly. App-root
  `*_tool_handlers.py` modules are compatibility aliases only.
- `application/platform/read_models.py`: platform read-model response contracts
  for documentation, build, dashboard, welcome, and project workspace views,
  plus `ReadModelSummaryService` for cross-domain summary policy used by
  dashboard, project, version, workspace, knowledge, system-image, run,
  governance, and conversation fallback text. App-root `models.py` may
  re-export these response DTOs during migration, but it must not define them;
  legacy `ApplicationStore` summary helpers are compatibility delegates only.
  `ReadModelSummaryService` receives `AgentQueryReadPort`; it must not retain the
  Store or inspect repositories directly.
- `application/platform/read_query_ports.py`: least-privilege read contracts for
  Agent query use cases and top-level portfolio content. The application layer
  owns these contracts; infrastructure translates compatibility projections to
  them through `CompatibilityPlatformQueryReadModel`.
- `application/platform/top_level_content.py`: platform-owned top-level studio
  read assembly for Welcome, Build, Dashboard, and Documentation. HTTP routes
  should reach these reads through `PlatformApplicationService`; legacy
  `ApplicationStore.get_welcome`, `get_build`, `get_dashboard`, and
  `list_documentation` are compatibility delegates only and must not assemble
  `WelcomeResponse`, `BuildResponse`, or `DashboardResponse` directly. During
  the compatibility phase, `ApplicationStore` must hold a constructor-injected
  `top_level_content` instance backed by `TopLevelContentReadPort` and delegate
  to it directly. The service must not retain `ApplicationStore`.
- `application/platform/demo_seed.py`: local/demo seed-data application
  component. It owns the Payment System seed project, version, US items,
  quality-loop lanes, run/approval examples, documentation examples,
  release-readiness example, system-image readiness seeding, and initial demo
  conversations. `ApplicationStore._seed` is a compatibility delegate only and
  must not contain demo object construction or repository write loops inline.
  It depends only on `DemoSeedWorkspacePort`. The local-only infrastructure
  adapter is `SQLAlchemyDemoSeedWorkspace`, which receives the owning
  repositories and conversation callback and writes idempotent durable facts.
  `CompatibilityDemoSeedWorkspace` remains migration-test only. Neither
  component may receive or inspect `ApplicationStore`. The compatibility facade delegates to the
  constructor-injected service and must not instantiate it inside `_seed`.
- `application/platform/PlatformApplicationService`: HTTP-facing platform
  facade for account, settings/model configuration, top-level studio reads,
  tool catalog, tool invocation, and audit queries. It must compose dedicated
  application services such as `AccountApplicationService`,
  `ModelConfigurationApplicationService`, `TopLevelContentApplicationService`,
  `ToolInvocationApplicationService`, and `PlatformAuditApplicationService`.
  It must not keep a `self._store` escape hatch, mutate `ApplicationStore`
  directly, or call compatibility-store methods inline.
- `application/platform/ProjectWorkspaceApplicationService`: project workspace
  BFF reads and project/version tool-backed writes. Project workspace
  read-model assembly, current-US selection, quality-loop state projection,
  workspace detail payloads, run detail reads, approval detail reads, and
  release-readiness reads belong here. `ApplicationStore.get_project_workspace`,
  `get_workspace_data`, `get_run_detail`, `get_approval_detail`, and
  `get_release_readiness` are compatibility delegates only and must not
  reintroduce inline workspace aggregation. `ApplicationStore` must not expose
  private project workspace facades such as `_current_task_context`,
  `_current_quality_profile`, `_current_quality_asset_pack`,
  `_current_release_decision`, `_quality_loop_state`, or
  `_select_project_workspace_us`. During the compatibility phase,
  `ApplicationStore` must hold a constructor-injected `project_workspace`
  instance and delegate to it directly; it must not expose
  `_project_workspace_app` factories or create this service inside workspace
  read methods.
- `application/platform/ProjectReadModelRefreshApplicationService`: platform
  read-boundary notification for committed project facts. Production composes
  `RepositoryBackedProjectReadModelProjection`; refresh is intentionally a
  no-op because every query reads PostgreSQL. The application service depends
  only on `ProjectReadModelProjectionPort`. The legacy
  `CompatibilityProjectReadModelProjection` and its mutable state/adapters are
  retained only for migration tests.
  `ApplicationStore._refresh_project_read_models` is compatibility-only and
  delegates back to the constructor-composed service. Project workspace and
  system-image ingestion adapters must receive that same service through
  constructor injection and must not create subordinate refresh services.
  The infrastructure adapter reads project/version data through
  `ProjectRepository`, system-image data through `SystemImageRepository`, and
  quality-loop data through `QualityLoopRepository`; it must not use
  `ProjectRepository` as a cross-context persistence gateway.
- `application/platform/ProjectStateLoaderApplicationService` and
  `ProjectStateHydrationPort` are legacy migration fixtures. Production
  composition must not instantiate them or define
  `_load_persisted_project_state`; no project-domain facts are copied into the
  process at startup.
- Agent runtime facts have no startup hydration layer. Conversation, links,
  goals, summaries, session knowledge, memory, swarms, ToolInvocation, and
  AuditEvent are queried from PostgreSQL for every use case. Production
  composition must not define `RuntimeStateLoaderApplicationService`,
  `RuntimeStateHydrationPort`, runtime compatibility dictionaries, or a
  Conversation projection sink. This keeps API replicas and Temporal workers
  coherent without process-local synchronization.

When a compatibility method becomes complex, extract the behavior into the
proper bounded context instead of adding more store logic.

- Observation-driven Agent plan changes cross the
  `application/agent/replanning.py` port. Graph runtimes may apply a governed
  `AgentReplanDecision`, but must not construct provider prompts, call an LLM
  adapter directly, or bypass `AgentPlanPolicy`.

- Official System Image materialization is fail-closed. The production
  `SystemImageService` must validate source-derived objects, relationships, and
  code-quality metrics with `domain/system_image/materialization.py`; it must
  never generate synthetic objects, fixture evidence, fallback relationships,
  or placeholder quality metrics to make a baseline appear ready. Local demo
  content is owned exclusively by `application/platform/demo_seed.py` and is
  disabled by production runtime configuration.

- Platform governance production commands use
  `infrastructure/platform/SQLAlchemyGovernanceWorkspace`. Approval,
  release-decision, merged-resolution, evidence, project, version, and task
  facts are read from PostgreSQL repositories, never from compatibility
  dictionaries. A single approval mutation and the derived project/version
  pending-approval counters are committed atomically by
  `SQLAlchemyGovernanceCommandRepository`. Application code must call
  `GovernanceWorkspacePort.save_approval`; it must not rebuild and replace the
  complete approval or version collection. `CompatibilityGovernanceWorkspace`
  is limited to isolated migration tests and is not composed by `ApplicationStore`.

## Migration Exit Criteria

`ApplicationStore` can stop being a main dependency when all of these are true:

- `interface/http/routers/*` depend only on application services.
- `application/*` use ports instead of concrete repositories.
- `domain/*` contains the state machines and policies for Agent, System Image,
  Quality Loop, and Platform governance.
- `infrastructure/persistence` owns SQLAlchemy models and repository adapters.
- Tests cover domain units, application use cases, infrastructure adapters, and
  public API contracts separately.

## New Code Checklist

- Pick one bounded context before adding a file.
- Put protocol-specific code under `interface`.
- Put orchestration and transaction-level decisions under `application`.
- Put pure policies, value objects, and state machines under `domain`.
- Put database, object storage, LLM, workflow, and runner code under `infrastructure`.
- Keep write operations traceable through `ToolInvocationRuntime`.
- Update `tests/test_ddd_boundaries.py` when changing a boundary deliberately.
