# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `01-localhost-vs-production/develop/app.py`
1. **Hardcoded secrets (lines 17–18):** `OPENAI_API_KEY` and `DATABASE_URL` with credentials are written directly in source code; pushing to Git exposes secrets immediately.
2. **Hardcoded non-externalized config (lines 21–22):** `DEBUG = True` and `MAX_TOKENS = 500` are constants in code instead of environment variables, making dev/staging/prod behavior rigid.
3. **Unstructured `print()` logging & secret leakage (lines 33–34, 38):** Uses `print()` instead of structured JSON logging, and line 34 logs `OPENAI_API_KEY` directly to stdout.
4. **No health/readiness endpoints (lines 42–43):** Missing `/health` (liveness) and `/ready` (readiness), so platforms/load balancers cannot detect crashes or readiness state.
5. **Localhost-only binding & hardcoded port (lines 51–52):** `host="localhost"` prevents external/container traffic, and `port=8000` ignores cloud-injected `PORT` env vars.
6. **Debug reload enabled in startup (line 53):** `reload=True` wastes resources and causes instability in production.
7. **No graceful shutdown / lifespan handling & no input/CORS controls:** Missing `SIGTERM` handler / `lifespan` cleanup and missing CORS / structured validation (query param `question: str` instead of JSON body schema).

### Exercise 1.2: Running basic version (`develop/app.py`)
Command run (per K5 Notice #3 using query param):
```bash
curl -i -X POST "http://localhost:8000/ask?question=Hello"
```
Output observed:
```text
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 07:24:53 GMT
server: uvicorn
content-length: 95
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```
Server stdout also leaked the secret: `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`.

### Exercise 1.3: Comparison table (`develop/app.py` vs `production/app.py` & `config.py`)
Test outputs on `production/app.py`:
- `GET /health` → `200 OK`: `{"status":"ok","uptime_seconds":1.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:24:54.190243+00:00"}`
- `GET /ready` → `200 OK`: `{"ready":true}`
- `POST /ask` (`{"question": "Hello"}`) → `200 OK`: `{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Why Important? |
|---------|----------------------------|------------------------------------------------|----------------|
| **Config & Secrets** | Hardcoded constants (`OPENAI_API_KEY`, `DATABASE_URL`, `PORT=8000`, `DEBUG=True`, lines 17–22, 51–53) | Read from env vars via `Settings` dataclass in `config.py` with `validate()` fail-fast check (lines 14–50) | Separates code from config (12-Factor), prevents leaking secrets in Git, and enables different settings per env (`dev`/`staging`/`prod`). |
| **Network Binding** | `host="localhost"`, `port=8000`, `reload=True` (lines 51–53) | `host=settings.host` (`0.0.0.0`), `port=settings.port` (`PORT` env), `reload=settings.debug` (lines 194–199) | `0.0.0.0` is required inside containers/cloud; dynamic `PORT` is injected by platforms like Railway/Render/Cloud Run. |
| **Health & Readiness** | None (lines 42–43) | `GET /health` (liveness, lines 135–149), `GET /ready` (readiness 503 until `is_ready=True`, lines 152–161), `GET /metrics` (lines 164–173) | Orchestrators/LBs use `/health` to restart crashed containers and `/ready` to avoid routing traffic before startup finishes or during shutdown. |
| **Logging** | `print()` statements, logs raw `OPENAI_API_KEY` (lines 33–34, 38) | `logging` configured with JSON format + `json.dumps` events (`question_length`, `client_ip`, no secrets) (lines 28–32, 111–122) | Structured JSON logs are machine-parseable for log aggregators (Loki, Datadog, Cloud Logging) and prevent credential exposure. |
| **Shutdown Lifecycle** | Abrupt exit, no cleanup | `lifespan` context sets `is_ready = False` & drains requests (lines 40–67) + `signal.signal(signal.SIGTERM, handle_sigterm)` (lines 180–189) | Allows in-flight requests to complete and connections to close cleanly during rolling deploys or scale-down without dropping user requests. |
| **CORS & Validation** | No CORS middleware; query param `question: str` | `CORSMiddleware` using `ALLOWED_ORIGINS` (lines 77–82); JSON body check returning 422 if `question` missing (lines 103–108) | Restricts browser cross-origin access to trusted domains and validates payloads cleanly. |

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)
1. **Base image:** `python:3.11` (line 8) — full Debian-based Python 3.11 image (~1 GB).
2. **Working directory:** `/app` (line 11: `WORKDIR /app`).
3. **Why copy `requirements.txt` before source code?** Docker builds layer-by-layer and caches unchanged layers. `requirements.txt` changes much less often than `app.py`, so copying and running `pip install` first reuses the dependency cache when only application code changes.
4. **`CMD` vs `ENTRYPOINT`:** `CMD` sets the default command/arguments that can be easily overridden at `docker run` time (e.g., `docker run my-agent bash`), whereas `ENTRYPOINT` defines the fixed executable that always runs (with `CMD` appended as default args).

### Exercise 2.2: Build and run (`my-agent:develop`)
Built from repo root (`docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`) and tested via query param:
```bash
curl -i -X POST "http://localhost:8000/ask?question=What+is+Docker"
```
Output:
```text
HTTP/1.1 200 OK
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & image size comparison
- **Stage 1 (`builder`, `python:3.11-slim`):** Installs OS build tools (`gcc`, `libpq-dev`) and compiles/installs Python dependencies into `/root/.local` via `pip install --user`.
- **Stage 2 (`runtime`, `python:3.11-slim`):** Creates non-root `appuser`, copies only `/root/.local` packages + `main.py` + `utils/mock_llm.py`, sets `PATH`, `USER appuser`, `HEALTHCHECK`, and runs `uvicorn`.
- **Why smaller:** Uses `slim` instead of the full `python:3.11` base, and discards `gcc`, `libpq-dev`, apt caches, and pip caches from the builder stage.

Measured with `docker images | grep my-agent`:
- **Develop (`my-agent:develop`):** `1.67 GB` (~1670 MB)
- **Production (`my-agent:advanced`):** `240 MB`
- **Difference:** **~85.6% reduction** (saved ~1.43 GB)

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)
Services started on internal bridge network `internal` (`redis`, `qdrant`, `agent`, `nginx`) with `touch .env.local` and `-p k5-day14-docker`:

```text
Client (HTTP :80)
   │
   ▼
Nginx (nginx:alpine, :80/:443, rate-limit 10r/s + security headers)
   │  proxy_pass http://agent_backend
   ▼
Agent (FastAPI + Uvicorn, :8000, non-root, depends_on healthy redis & qdrant)
   ├──► Redis (redis:7-alpine, :6379, session cache & rate limiting)
   └──► Qdrant (qdrant/qdrant:v1.9.0, :6333, vector DB for RAG)
```

Test results through Nginx (`http://localhost`):
- `GET http://localhost/health` → `200 OK` (`Server: nginx`, `X-Frame-Options: DENY`): `{"status":"ok","uptime_seconds":5.9,"version":"2.0.0","timestamp":"2026-11-26T07:38:27.897815"}`
- `POST http://localhost/ask` (`{"question": "Explain microservices"}`) → `200 OK`: `{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}`

## Part 3: Cloud Deployment
*(Completed after Part 6 in CP6 — URL, Railway vs Render comparison, Cloud Run CI/CD summary, and screenshots will be added here.)*

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)
- **Where API key is checked:** `verify_api_key` dependency (`lines 39–54`) using `APIKeyHeader(name="X-API-Key", auto_error=False)`, injected into `POST /ask` via `Depends(verify_api_key)` (`line 70`).
- **Missing / invalid key behavior:** Missing header returns `401 Unauthorized` (`lines 44–48`); wrong key returns `403 Forbidden` (`lines 49–53`).
- **How to rotate keys:** Read keys from environment variables (`AGENT_API_KEY`) or a secret manager; support multiple active keys (`ALLOWED_KEYS` list/set) during rotation so the new key is deployed and distributed to clients before revoking the old key.

Test output (`AGENT_API_KEY=secret-key-123 python app.py`):
```text
# Missing key -> 401
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Wrong key -> 403
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Valid key -> 200
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/auth.py`)
- **Flow:** Client authenticates with `POST /auth/token` (`student` / `demo123`) to receive an HS256-signed JWT containing `sub`, `role`, `iat`, `exp` (60 min expiry). Subsequent `POST /ask` requests send `Authorization: Bearer <token>`, verified statelessly by `verify_token` (`lines 46–67`).
- **Test output (token masked):**
```text
# Missing token -> 401
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Login POST /auth/token -> 200 (token masked)
TOKEN_PREVIEW=eyJhbGciOiJIUzI1...ewhk4KKQ

# Valid Bearer token -> 200
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
```

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)
- **Algorithm:** Sliding Window Counter (`lines 17–71`) using a per-user `collections.deque` of request timestamps inside a `60s` window (evicting timestamps older than `now - window_seconds`).
- **Limit:** `10 requests / 60 seconds` for standard users (`rate_limiter_user`, `line 86`), and `100 requests / 60 seconds` for admins (`rate_limiter_admin`, `line 87`).
- **Bypass / higher limit for admin:** Check `role == "admin"` in the endpoint and apply `rate_limiter_admin` (or skip rate limiting altogether for admin/internal service roles).
- **Test output (requests 1–12 after initial test request, token masked):**
```text
req 1..9  -> HTTP 200 | requests_remaining: 8 down to 0
req 10    -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
req 11    -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
req 12    -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard (`04-api-gateway/production/cost_guard.py`) & Rate Limit vs Cost Guard
- **Approach:** Track per-user (and global) daily LLM token usage (`input_tokens` at `$0.00015/1K`, `output_tokens` at `$0.0006/1K`) against `daily_budget_usd` (`$1.0`) and `global_daily_budget_usd` (`$10.0`). Before calling the LLM, `check_budget(user_id)` warns at 80% usage and raises `402 Payment Required` if user daily budget is exceeded (or `503` if global budget is exceeded); after the LLM responds, `record_usage()` adds actual token cost. In production (Part 6), state is stored in **Redis** (`INCRBYFLOAT` + key TTL) instead of in-memory dicts so limits survive restarts and work across multiple workers/instances.
- **Why both Rate Limit and Cost Guard are needed:** Rate limiting protects **request velocity / availability** (requests per minute, preventing spam/DDoS), whereas Cost Guard protects **financial budget** (cumulative token spend over a day/month — e.g., a few large-token prompts can stay under the RPM limit while still exhausting the API budget).

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health checks & Graceful shutdown (`05-scaling-reliability/develop/app.py`)
- **Liveness probe (`GET /health`, lines 104–145):** "Agent có còn sống không?". Returns `200 OK` with uptime, checks, and timestamp. If this endpoint fails or times out, the platform/orchestrator (Docker/K8s/Railway) automatically restarts the container.
- **Readiness probe (`GET /ready`, lines 147–169):** "Agent có sẵn sàng nhận request chưa?". Returns `200 OK` when `_is_ready = True` and dependencies are ready; returns `503 Service Unavailable` during startup ("Đang khởi động (model chưa load xong)"), shutdown ("Đang shutdown"), or when dependencies/database have not connected. Load balancers use this to route or temporarily stop routing traffic without killing the process.
- **Graceful shutdown (`SIGTERM`, lines 41–67, 175–189):**
  - Handled via `signal.signal(signal.SIGTERM, handle_sigterm)` and `lifespan`: sets `_is_ready = False` so LB stops sending new traffic, then executes a drain loop (`while _in_flight_requests > 0`) up to 30s so active requests finish cleanly before exit code 0.
- **Actual test output:**
```text
# GET /health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:47:42.409552+00:00","checks":{"memory":{"status":"ok","used_percent":23.3}}}

# GET /ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

# kill -TERM $PID
2026-11-26 14:47:42,612 INFO 🔄 Graceful shutdown initiated...
2026-11-26 14:47:42,613 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
2026-11-26 14:47:42,613 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

### Exercise 5.3, 5.4 & 5.5: Stateless architecture & test stateless (`05-scaling-reliability/production`)
- **Stateless design:** Avoids "State trong memory" (which breaks when scaling across multiple instances or on container restart). All session state and conversation history are persisted in Redis (`redis:7-alpine`).
- **Load balancing:** Nginx round-robins requests across 3 scaled agent instances (`agent=3`) on port 8080 (`POST /chat`).
- **`python test_stateless.py` output:**
```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 6cdfa045-2b79-4d66-8e39-3468b289562d

Request 1: [instance-50b377]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-853938]
  Q: Why do we need containers?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 3: [instance-a63de3]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-50b377]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-853938]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-a63de3', 'instance-50b377', 'instance-853938'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```
- **Conclusion:** All 5 requests were served across 3 different instances (`instance-a63de3`, `instance-50b377`, `instance-853938`), and the full conversation history of 10 messages was preserved across all instances via Redis.

## Part 6: Final Project (`06-lab-complete/`)

### `python check_production_ready.py` Output
```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```
