# 03 Engineering Platform

## Mandate

Own reliable implementation across FastAPI, storage, workers, data adapters,
tests, and Vercel deployment.

## Responsibilities

- public and member API contracts
- storage repository and migrations
- worker queue processing
- chart payload and stock payload builders
- ticker resolver and vendor adapters
- deployment-safe environment handling

## Engineering Standards

- Keep route handlers thin; delegate to testable builders/services.
- Use structured parsers and typed payload shapes where practical.
- Keep external API tests optional or mocked.
- Add tests proportional to risk and blast radius.
- Preserve US-market fallback paths unless a scoped task changes them.

## Default Commands

```powershell
$env:UV_PROJECT_ENVIRONMENT='.codex-test-venv'
uv run --with pytest pytest -q
```

