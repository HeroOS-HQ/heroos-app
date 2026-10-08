# HeroOS Observability: Privacy-Safe Logging and Errors

**Status:** Implemented (M1-07) and proven locally. CloudWatch ingestion deferred to M5 (cloud activation; [Delivery Plan](../milestones/delivery-plan.md))\
**Owner:** Technical Lead\
**Milestone:** M1 — Foundation & Security\
**Issue:** M1-07 — Establish secure storage, secrets, logging & backup foundation\
**Related:** [Security Boundaries](security-boundaries.md), [Authentication §7](authentication.md#7-credential-logging)

## 1. Principle

Operational logs must make failures **detectable and investigable** without
becoming a second copy of HR data. HeroOS logs opaque identifiers, route
templates, status codes, timings and exception *types and locations*. It never
logs request content.

`app/observability/`:

| Module | Responsibility |
| --- | --- |
| `logging.py` | `StructuredFormatter` (JSON lines), `RequestContextFilter`, `configure_logging`, `sanitized_exception` |
| `middleware.py` | `RequestObservabilityMiddleware`: request ID, `request_completed`, the unhandled-error boundary |
| `context.py` | per-request correlation context (`ContextVar`) |
| `__init__.py` | `install_observability(app)`: middleware plus the safe 422 handler |

`app/main.py` calls `configure_logging(HEROOS_LOG_LEVEL)` before anything else
logs, and then `install_observability(app)`.

## 2. Log format

One JSON object per line on **stdout**, ready for container log collection
(CloudWatch in M5). Example:

```json
{"timestamp":"2026-10-08T14:28:44.841+00:00","level":"INFO","logger":"app.request","event":"request_completed","request_id":"c0768019054e0f772635976bef9fff99","method":"GET","route":"/companies/{company_id}/cases","status_code":200,"duration_ms":1.75,"company_id":"…","user_id":"…"}
```

### Fields that are intentionally logged

| Field | Content |
| --- | --- |
| `timestamp`, `level`, `logger` | record metadata |
| `event` | fixed event name: `request_completed`, `unhandled_exception` |
| `request_id` | server-generated 32-hex ID, also in `X-Request-ID` |
| `method` | HTTP method from a fixed set (otherwise `OTHER`) |
| `route` | the matched **route template** (`/companies/{company_id}/cases/{case_id}`), or `<unmatched>` |
| `status_code`, `duration_ms` | outcome and latency |
| `company_id`, `user_id` | opaque UUIDs, recorded **only after** Membership authorization succeeds |
| `error_id` | 32-hex ID returned to the client with a 500 |
| `exception_type`, `exception_chain`, `exception_frames` | qualified class names, plus up to 10 frames of `{file: basename, line, function}` |
| `message` | for records without an `event` only: HeroOS fixed-reason messages (for example `Authentication rejected: cognito token rejected (ExpiredSignatureError)`) and library lifecycle messages (`Started server process`) |

Only these allowlisted fields are emitted. Any other `extra` attached to a
record is dropped by the formatter.

### Data that is intentionally excluded

- `Authorization` headers, bearer JWTs and token fragments, `Cookie` /
  `Set-Cookie`, API keys, passwords and any other header (no header is logged)
- secret configuration values, `DATABASE_URL` / `MIGRATION_DATABASE_URL`
  (`SecretStr`)
- raw request bodies and response bodies (there is no body-logging middleware)
- the raw path and the query string, which can carry names or identifiers.
  Only the route template is logged
- uploaded file and document content, object keys, storage paths
- employee names, case narratives and facts, HR guidance input/output
- exception **messages**, tracebacks, frame locals and source lines
- SQL statements and bound parameters

## 3. Request correlation

- `RequestObservabilityMiddleware` (pure ASGI) generates a request ID per HTTP
  request with `secrets.token_hex(16)`. A client-supplied `X-Request-ID` is
  ignored and never logged, so clients cannot inject log content or forge
  correlation.
- The ID is returned in the `X-Request-ID` response header (500 responses
  included) and stamped on every log record emitted during the request, by a
  logging filter. That covers authentication and authorization logs too.
- `request_completed` is logged for every request (INFO; WARNING for 5xx).

## 4. Unhandled-error boundary

Any exception that escapes the application reaches the middleware, which:

1. creates an `error_id`;
2. logs one `unhandled_exception` event (ERROR) with `request_id`, `error_id`,
   method, route template and `sanitized_exception(exc)`: the exception type, the
   cause-chain types and code locations. It **never** includes the message, which
   can contain user-supplied values;
3. returns `500 {"detail": "Internal server error", "request_id": "…", "error_id": "…"}`;
4. does **not** re-raise. Otherwise the server would log a full traceback.

The formatter applies the same rule to every record that carries `exc_info`
(for example Uvicorn lifespan errors). `formatException` and `formatStack` never
render a traceback. Fixed-message HeroOS errors (`StorageError`,
`UnsafeDatabaseRoleError`, …) are identified by their type.

Expected outcomes are **not** error events: 401, 403, 404, 405 and 422 (and any
deliberate `HTTPException`) produce only `request_completed`. M1-05/M1-06
generic responses are unchanged. 422 responses keep `type`, `loc` and `msg` but
drop the submitted `input` and `ctx`, because FastAPI otherwise echoes the
submitted value back. If code ever serializes a pydantic `ValidationError`
itself, it must use `errors(include_input=False)` /
`json(include_input=False)`. `str(...)`, which is what startup failures print, is
already safe because `hide_input_in_errors=True`.

## 5. Server, database and client logs

- **Uvicorn access log is off.** It records the raw request target, including
  the query string. The official command (`apps/api/Dockerfile`, and the README
  for local runs) passes `--no-access-log`, and `configure_logging` also
  disables the `uvicorn.access` logger, so the protection does not depend on the
  flag. `request_completed` is the authoritative request log. Uvicorn's other
  records (startup, shutdown, errors) flow through the structured formatter.
  Verified against a real Uvicorn process with and without the flag.
- **SQLAlchemy** `echo` is never enabled. The `sqlalchemy` loggers are pinned to
  WARNING whatever `HEROOS_LOG_LEVEL` is, so SQL and bound parameters (HR data)
  never reach the log, even at DEBUG.
- **HTTP clients** (`httpx`, `httpcore`, `urllib3`) are pinned to WARNING. Their
  INFO records contain full URLs with query strings.
- `HEROOS_LOG_LEVEL` (`DEBUG` | `INFO` | `WARNING` | `ERROR`, default `INFO`)
  changes verbosity only. Redaction does not depend on the level, and the
  leakage tests run at DEBUG.

Residual risk: library records without an `event` keep their message text.
Current libraries only emit lifecycle messages there. Any new dependency that
logs request data at INFO or below must be pinned in `QUIETED_LOGGERS`.

## 6. Rules for new code

- Log with a fixed event name and allowlisted fields:
  `logger.info("event_name", extra={"event": "event_name", ...})`. To add a
  field, add it to `SAFE_FIELDS` in review.
- Never format request content, model fields, exception messages or object
  bytes into a log message.
- Never use `logger.exception` / `exc_info=True` to get "more detail". The
  formatter strips the message anyway, so log the event and let `error_id`
  correlate it.
- Do not add request/response body or header logging middleware.

## 7. Tests

| File | Proves |
| --- | --- |
| `tests/observability/test_structured_logging.py` | JSON format and field allowlist; no exception message, traceback, `stack_info` or full path; cause-chain types only; idempotent configuration; risky loggers quieted and the access log disabled; SQLAlchemy logs no SQL or parameters at DEBUG; request IDs generated, unique, returned and logged; client request IDs ignored; route template rather than raw path, `<unmatched>` for unknown paths; 401/403/404/422 are not error events; 422 does not echo input; generic 500 with matching `request_id`/`error_id` for sync and async failures and after a response has started; the real app is wired; the Dockerfile disables the access log |
| `tests/observability/test_sensitive_data_leakage.py` | synthetic canaries (bearer, password, cookie, API key, employee name, case narrative, document body, query, storage path) are absent from formatted logs, raw log records, response bodies and headers for: success, 401, 403, 422, unmatched 404, an unhandled error whose message contains request data, a storage failure, a cross-Company object miss, a configuration validation error and startup failure output |

Mutation checks (M1-07). Each of these made the suites fail: logging the
`Authorization` header, logging the raw path and query string, logging the
request body, logging the exception message, rendering full tracebacks,
echoing validation input, and re-enabling the Uvicorn access log.

## 8. Deferred to M5

CloudWatch log groups and ingestion from ECS stdout, log retention (PRIV-006),
metric filters and alarms for 5xx and `unhandled_exception`, and any
third-party error-monitoring service. A third-party service would need a
service-inventory entry and privacy review first. See
[Production Security Gates](production-security-gates.md).
