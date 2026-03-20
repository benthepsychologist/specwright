---
name: local-http-smoke-test
description: Start a real local HTTP server process, send curl requests to live endpoints, and assert status codes and response content for quick smoke validation.
metadata:
  author: benthepsychologist
  version: "1.0"
allowed-tools: bash curl
---

# Local HTTP Smoke Test

Use this skill to verify service startup and core endpoint behavior.

## Start service

```bash
PORT=8081 ./scripts/start-server.sh
```

Run the real service command, not a mocked server.

## Probe endpoints

```bash
curl -sS -o /tmp/health.out -w "%{http_code}" "http://127.0.0.1:8081/health"
curl -sS -o /tmp/root.out   -w "%{http_code}" "http://127.0.0.1:8081/"
```

Expected status is typically `200` unless project docs state otherwise.

## Assert body content

```bash
rg -n "ok|healthy|ready" /tmp/health.out
rg -n "<expected-key-or-text>" /tmp/root.out
```

## Failure triage

- If connection fails: verify process and listening port.
- If status mismatches: capture body and server logs.
- Stop process cleanly when done.
