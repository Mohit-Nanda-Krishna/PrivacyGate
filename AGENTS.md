# PrivacyGate Agent Instructions

PrivacyGate is a pre-LLM privacy firewall for business documents.

## Core Rules

- Follow the existing architecture and technology stack.
- Prefer simple, maintainable implementations.
- Do not make unrelated changes.
- Do not replace working modules unnecessarily.
- Preserve existing module interfaces unless explicitly asked to change them.
- Add or update tests for functional changes.
- Run relevant tests before finishing a task.
- Never intentionally send raw PII to an external LLM.
- Never unnecessarily log or persist raw PII.
- Security-critical failures must fail closed.
- Do not mark unsafe or failed processing as "Approved".
- Never silently hide failing tests or unresolved errors.

## Project Context

Read `PRD.md` when:
- implementing a new major feature,
- changing architecture or technology choices,
- changing module interfaces,
- modifying privacy/security behavior,
- requirements are unclear.

Read `PROGRESS.md` when:
- continuing previous work,
- starting a new development phase,
- current implementation status matters.

For small isolated fixes, inspect the relevant code and tests instead of rereading the entire PRD.

## Progress Tracking

After substantial work, update `PROGRESS.md` with:
- what was completed,
- tests/results,
- known issues,
- next recommended task.

## Dependency Management

- Python version is locked to Python 3.11.
- Use `uv` for dependency management.
- `pyproject.toml` and `uv.lock` are the dependency source of truth.
- Do not manually edit `uv.lock`.
- Add dependencies using `uv add`.
- Do not introduce new dependencies unless required by the task.
- Do not replace existing libraries without explicit approval.
- Core functionality must not depend on external API keys.

Do not rewrite historical progress unnecessarily.