# Runtime Validation Report

**Generated**: 2026-11-08T22:04:00+01:00
**Target**: `/home/zenda/gta_Automation`

## Summary

| Step | Status | Exit Code | Details |
|---|---:|---:|---|
| Python compilation | PASS | 0 | `app`, `pipeline`, and `tests` compiled successfully |
| Integration tests | PASS | 0 | 66 tests passed, 1 upstream deprecation warning |
| Isolated startup | PASS | 0 | Uvicorn started on port 18000; `/health` returned 200 |
| Health detail | PASS | 0 | Database integrity `ok`; FFmpeg and FFprobe available |
| Dashboard HTTP | PASS | 0 | `/` returned HTTP 200 and HTML |
| OpenAPI HTTP | PASS | 0 | `/openapi.json` returned HTTP 200 and JSON |
| Pipeline CLI | PASS | 0 | `python -m pipeline.run --help` listed all commands |
| Browser smoke | PASS | 0 | Chromium captured the dashboard at 1280x720 |

**Overall**: PASS

## Environment

```text
Python: 3.14.4 (.venv)
pytest: 8.4.2
Docker: available and daemon responding
Node.js: v26.8.1
Playwright: 1.65.0
FFmpeg: 8.0.1-3ubuntu2
FFprobe: 8.0.1-3ubuntu2
```

## Verification Notes

- The canonical suite was `.venv/bin/python -m pytest -q`.
- The existing process on `127.0.0.1:8000` was left untouched. Attempting to launch another instance there correctly failed with `address already in use`.
- A fresh instance was started and verified on port `18000`, then stopped cleanly.
- The only test-suite warning is a dependency compatibility warning from Starlette about `httpx`; it does not currently fail tests.

## Verdict

```text
environment:
  docker: AVAILABLE — daemon responded to docker info
  node: AVAILABLE — v26.8.1
  playwright: AVAILABLE — Chromium installed and screenshot completed
  infra-tier: PRIMARY(Docker-based) — available; no external container dependency required by this test suite
  browser-tier: PRIMARY(Playwright) — dashboard rendered successfully
startup: PASS — .venv/bin/uvicorn app.main:app, /health returned 200 on port 18000
integration: PASS — exit_code: 0, passed: 66, failed: 0, skipped: 0
e2e: PASS — exit_code: 0, dashboard browser smoke flow completed
overall: PASS — all executed verification layers succeeded
```
