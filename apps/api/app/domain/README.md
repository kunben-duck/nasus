# Backend Domain Layer

The domain layer contains pure product rules for Nasus bounded contexts.

## Allowed

- Python standard library imports such as `dataclasses`, `typing`, `hashlib`, and `re`.
- Relative imports inside `apps/api/app/domain`.
- Entities, value objects, policies, state machines, and deterministic domain services.
- Protocol-style inputs that describe the minimum attributes a policy needs.

## Forbidden

- FastAPI, SQLAlchemy, Pydantic, object storage, LLM clients, Temporal, LangGraph, HTTP clients, and environment configuration.
- `ApplicationStore`, repositories, ORM models, runtime adapters, tool handlers, and global service singletons.
- Persistence, network calls, object storage reads/writes, token accounting, or workflow execution.

Application services are responsible for gathering data, calling domain policies, mapping decisions into API DTOs, and coordinating persistence.
