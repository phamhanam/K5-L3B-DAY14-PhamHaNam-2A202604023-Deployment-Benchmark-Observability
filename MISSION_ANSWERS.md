# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Các anti-pattern tìm thấy trong `01-localhost-vs-production/develop/app.py`
1. **Hardcode secret trong source code (dòng 17–18):** `OPENAI_API_KEY` và `DATABASE_URL` chứa thông tin xác thực được viết thẳng vào code; nếu push lên Git sẽ bị lộ ngay lập tức.
2. **Cấu hình cố định trong code (dòng 21–22):** `DEBUG = True` và `MAX_TOKENS = 500` không đọc từ biến môi trường, khiến việc đổi cấu hình giữa dev/staging/production thiếu linh hoạt.
3. **Dùng `print()` thay cho structured logging và làm lộ secret (dòng 33–34, 38):** Ghi log dạng text thuần bằng `print()`, đặc biệt dòng 34 in thẳng `OPENAI_API_KEY` ra stdout.
4. **Thiếu endpoint health/readiness check (dòng 42–43):** Không có `/health` (liveness) và `/ready` (readiness), nên platform hoặc load balancer không thể phát hiện khi agent bị treo hay chưa sẵn sàng.
5. **Bind `localhost` và hardcode cổng `8000` (dòng 51–52):** `host="localhost"` chặn kết nối từ bên ngoài container, còn `port=8000` bỏ qua biến `PORT` do nền tảng cloud cấp.
6. **Bật `reload=True` khi chạy app (dòng 53):** Chế độ debug watch file gây tốn tài nguyên và không ổn định trên production.
7. **Thiếu graceful shutdown, CORS và schema validation:** Không xử lý `SIGTERM`/`lifespan` để hoàn thành request đang chạy khi tắt, không cấu hình CORS và nhận `question` qua query param thay vì JSON body có kiểm tra hợp lệ.

### Exercise 1.2: Chạy bản develop (`develop/app.py`)
Lệnh gọi (theo Lưu ý số 3 của lớp K5 — truyền `question` qua query):
```bash
curl -i -X POST "http://localhost:8000/ask?question=Hello"
```
Output thực tế:
```text
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 07:24:53 GMT
server: uvicorn
content-length: 95
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```
Ngoài ra, console của server còn in lộ secret: `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`.

### Exercise 1.3: Bảng so sánh (`develop/app.py` vs `production/app.py` & `config.py`)
Kết quả test thực tế trên `production/app.py`:
- `GET /health` → `200 OK`: `{"status":"ok","uptime_seconds":1.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:24:54.190243+00:00"}`
- `GET /ready` → `200 OK`: `{"ready":true}`
- `POST /ask` (`{"question": "Hello"}`) → `200 OK`: `{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}`

| Thành phần | Bản Develop (`develop/app.py`) | Bản Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode hằng số (`OPENAI_API_KEY`, `DATABASE_URL`, `PORT=8000`, `DEBUG=True`, dòng 17–22, 51–53) | Đọc từ biến môi trường qua `Settings` dataclass trong `config.py` kèm hàm `validate()` fail-fast (dòng 14–50) | Tách biệt code và cấu hình (12-Factor), tránh lộ secret trên Git và dễ đổi cấu hình giữa `dev`/`staging`/`prod`. |
| **Network Binding** | `host="localhost"`, `port=8000`, `reload=True` (dòng 51–53) | `host=settings.host` (`0.0.0.0`), `port=settings.port` (biến `PORT`), `reload=settings.debug` (dòng 194–199) | Bắt buộc bind `0.0.0.0` để nhận traffic bên ngoài container; cloud platform tự inject cổng qua `PORT`. |
| **Health & Readiness** | Không có (dòng 42–43) | `GET /health` (liveness, dòng 135–149), `GET /ready` (readiness trả 503 khi `is_ready=False`, dòng 152–161), `GET /metrics` (dòng 164–173) | Orchestrator/LB dùng `/health` để restart container lỗi và `/ready` để không đẩy traffic vào instance chưa sẵn sàng hoặc đang tắt. |
| **Logging** | Dùng `print()`, log lộ `OPENAI_API_KEY` (dòng 33–34, 38) | Dùng `logging` định dạng JSON + `json.dumps` (`question_length`, `client_ip`, không log secret) (dòng 28–32, 111–122) | Structured JSON logs dễ tìm kiếm, lọc và phân tích trên hệ thống tập trung (Loki, Datadog, Cloud Logging), đồng thời tránh rò rỉ thông tin nhạy cảm. |
| **Shutdown Lifecycle** | Tắt đột ngột, không dọn dẹp | `lifespan` gán `is_ready = False` & chờ request hoàn thành (dòng 40–67) + `signal.signal(signal.SIGTERM, handle_sigterm)` (dòng 180–189) | Giúp các request đang xử lý (in-flight) hoàn tất và đóng kết nối sạch sẽ khi rolling deploy hoặc scale down, không làm rớt request của người dùng. |
| **CORS & Validation** | Không có CORS; nhận query param `question: str` | `CORSMiddleware` đọc từ `ALLOWED_ORIGINS` (dòng 77–82); kiểm tra JSON body và trả 422 nếu thiếu `question` (dòng 103–108) | Kiểm soát truy cập cross-origin từ frontend hợp lệ và chuẩn hoá kiểm tra đầu vào. |

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về Dockerfile (`02-docker/develop/Dockerfile`)
1. **Base image:** `python:3.11` (dòng 8) — bản phân phối Python 3.11 đầy đủ trên Debian (~1 GB).
2. **Working directory:** `/app` (dòng 11: `WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` trước source code?** Docker build theo từng layer và cache các layer không đổi. File `requirements.txt` ít thay đổi hơn `app.py`, nên copy và chạy `pip install` trước giúp tái sử dụng cache thư viện mỗi khi chỉ sửa code ứng dụng.
4. **Khác nhau giữa `CMD` và `ENTRYPOINT`:** `CMD` định nghĩa lệnh/tham số mặc định và dễ bị ghi đè khi chạy `docker run` (vd `docker run my-agent bash`), còn `ENTRYPOINT` cố định chương trình chính luôn được chạy (các tham số ở `CMD` sẽ được nối thêm vào sau `ENTRYPOINT`).

### Exercise 2.2: Build và chạy (`my-agent:develop`)
Build từ gốc repo (`docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`) và gọi thử với query param:
```bash
curl -i -X POST "http://localhost:8000/ask?question=What+is+Docker"
```
Output thực tế:
```text
HTTP/1.1 200 OK
server: uvicorn
content-length: 103
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & so sánh dung lượng image
- **Stage 1 (`builder`, `python:3.11-slim`):** Cài bộ công cụ build (`gcc`, `libpq-dev`) và cài Python dependencies vào `/root/.local` bằng `pip install --user`.
- **Stage 2 (`runtime`, `python:3.11-slim`):** Tạo user non-root `appuser`, chỉ copy thư viện từ `/root/.local` cùng `main.py` và `utils/mock_llm.py`, thiết lập `PATH`, `USER appuser`, `HEALTHCHECK` rồi chạy `uvicorn`.
- **Tại sao image nhỏ hơn:** Dùng base `slim` gọn hơn `python:3.11` đầy đủ, đồng thời loại bỏ hoàn toàn `gcc`, `libpq-dev`, apt cache và build artifacts ở stage builder.

Số liệu đo bằng `docker images | grep my-agent`:
- **Develop (`my-agent:develop`):** `1.67 GB` (~1670 MB)
- **Production (`my-agent:advanced`):** `240 MB`
- **Chênh lệch:** **Giảm ~85.6%** (tiết kiệm ~1.43 GB)

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)
Khởi chạy các service trên bridge network nội bộ `internal` (`redis`, `qdrant`, `agent`, `nginx`) sau khi `touch .env.local` và chạy với `-p k5-day14-docker`:

```text
Client (HTTP :80)
   │
   ▼
Nginx (nginx:alpine, :80/:443, rate-limit 10r/s + security headers)
   │  proxy_pass http://agent_backend
   ▼
Agent (FastAPI + Uvicorn, :8000, non-root, depends_on healthy redis & qdrant)
   ├──► Redis (redis:7-alpine, :6379, session cache & rate limiting)
   └──► Qdrant (qdrant/qdrant:v1.9.0, :6333, vector DB cho RAG)
```

Kết quả test qua Nginx (`http://localhost`):
- `GET http://localhost/health` → `200 OK` (`Server: nginx`, `X-Frame-Options: DENY`): `{"status":"ok","uptime_seconds":5.9,"version":"2.0.0","timestamp":"2026-11-26T07:38:27.897815"}`
- `POST http://localhost/ask` (`{"question": "Explain microservices"}`) → `200 OK`: `{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}`

---

## Part 3: Cloud Deployment

### Exercise 3.2: Deploy lên Render (`06-lab-complete/` — Agent Part 6)
- **URL public:** https://day14-ai-agent-0x1a.onrender.com
- **Nền tảng:** Render (gói Free Docker Web Service với Root Directory `06-lab-complete` + Free Render Key Value / Redis nối qua biến môi trường `REDIS_URL`)
- **Ảnh chụp màn hình:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`
- **Kết quả 4 lệnh tự kiểm CP6 trên URL public:**
```text
GET  /health                     -> 200  {"status":"ok","environment":"production"}
GET  /ready                      -> 200  {"status":"ready"}
POST /ask (không X-API-Key)      -> 401
POST /ask (có X-API-Key)         -> 200  {"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### So sánh `railway.toml` và `render.yaml`
| Tiêu chí | `railway.toml` | `render.yaml` |
|---|---|---|
| **Định dạng & phạm vi** | File TOML (`[build]`, `[deploy]`), cấu hình build/deploy cho một service đơn lẻ. | File YAML Infrastructure-as-Code Blueprint (`services:`), khai báo đồng bộ nhiều service (web service + managed Redis/Key Value, disk, envVars). |
| **Builder / Runtime** | `builder = "DOCKERFILE"` (hoặc `NIXPACKS`) kèm `dockerfilePath`. | `runtime: docker` (hoặc `python` với `buildCommand` / `startCommand`), `plan: free`, `region`. |
| **Health check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries`. | `healthCheckPath: /health` (tự động restart khi health check lỗi). |
| **Biến môi trường & Secret** | Không khai báo biến môi trường trong `railway.toml`; cấu hình riêng qua Dashboard hoặc `railway variables set`. | Khai báo ngay trong `envVars:` bằng `value:` cho biến thường và `generateValue: true` / `sync: false` cho secret để không lộ lên Git. |
| **Thư mục con (Subdirectory)** | Chọn root directory trong cấu hình service hoặc chạy `railway up` trực tiếp trong `06-lab-complete/`. | Hỗ trợ `rootDir` hoặc đặt Web Service Docker trỏ tới thư mục con `06-lab-complete`. |

### Exercise 3.3: Pipeline CI/CD GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)
1. **Test (`cloudbuild.yaml` bước 1):** Cài `requirements.txt` và `pytest` trong `python:3.11-slim`, chạy `pytest tests/ -v` để kiểm tra tự động trước khi build.
2. **Build (`bước 2`):** Build Docker image gắn tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, tận dụng `--cache-from` để cache layer.
3. **Push (`bước 3`):** Đẩy các tag image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`bước 4`):** Deploy image `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`, `min-instances=1`, `max-instances=10`, `512Mi`, `1 CPU`, `ENVIRONMENT=production`, và lấy `OPENAI_API_KEY` từ Secret Manager).
5. **Service IaC (`service.yaml`):** Mô tả khai báo Knative `Service` (`containerConcurrency: 80`, `minScale: 1`, `maxScale: 10`), tham chiếu secret qua `secretKeyRef`, cùng `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)
- **Chỗ kiểm tra API key:** Dependency `verify_api_key` (dòng 39–54) dùng `APIKeyHeader(name="X-API-Key", auto_error=False)`, gắn vào `POST /ask` qua `Depends(verify_api_key)` (dòng 70).
- **Khi thiếu hoặc sai key:** Thiếu header trả `401 Unauthorized` (dòng 44–48); sai key trả `403 Forbidden` (dòng 49–53).
- **Cách rotate key an toàn:** Đọc key từ biến môi trường (`AGENT_API_KEY`) hoặc secret manager; hỗ trợ tạm thời danh sách nhiều key hợp lệ (`ALLOWED_KEYS`) trong giai đoạn chuyển đổi để client cập nhật key mới trước khi thu hồi key cũ.

Kết quả test (`AGENT_API_KEY=secret-key-123 python app.py`):
```text
# Không có key -> 401
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key -> 403
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Có key hợp lệ -> 200
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/auth.py`)
- **Luồng hoạt động:** Client đăng nhập tại `POST /auth/token` (tài khoản `student` / `demo123`) để nhận JWT ký bằng thuật toán HS256 chứa `sub`, `role`, `iat`, `exp` (hết hạn sau 60 phút). Khi gọi `POST /ask`, client gửi header `Authorization: Bearer <token>`, hàm `verify_token` (dòng 46–67) xác minh chữ ký stateless mà không cần truy vấn DB mỗi request.
- **Kết quả test (đã che token):**
```text
# Thiếu token -> 401
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Đăng nhập POST /auth/token -> 200 (đã che token)
TOKEN_PREVIEW=eyJhbGciOiJIUzI1...ewhk4KKQ

# Có Bearer token hợp lệ -> 200
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
```

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)
- **Thuật toán sử dụng:** Sliding Window Counter (dòng 17–71) dùng `collections.deque` lưu timestamp các request của từng `user_id` trong cửa sổ `60s` (xoá các timestamp cũ hơn `now - window_seconds`).
- **Giới hạn:** `10 requests / 60 giây` cho user thường (`rate_limiter_user`, dòng 86) và `100 requests / 60 giây` cho admin (`rate_limiter_admin`, dòng 87).
- **Cách bypass / nới limit cho admin:** Kiểm tra `role == "admin"` trong endpoint để dùng `rate_limiter_admin` hoặc bỏ qua bước kiểm tra rate limit đối với role quản trị/nội bộ.
- **Kết quả vòng lặp 12 request (sau 1 request test ở 4.2, đã che token):**
```text
req 1..9  -> HTTP 200 | requests_remaining giảm từ 8 về 0
req 10    -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
req 11    -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
req 12    -> HTTP 429 | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard (`04-api-gateway/production/cost_guard.py`) & Vì sao cần cả Rate Limit và Cost Guard
- **Cách cài đặt:** Theo dõi lượng token LLM tiêu thụ theo ngày (`input_tokens` giá `$0.00015/1K`, `output_tokens` giá `$0.0006/1K`) đối chiếu với `daily_budget_usd` (`$1.0`) và `global_daily_budget_usd` (`$10.0`). Trước khi gọi LLM, `check_budget(user_id)` cảnh báo khi đạt 80% và trả `402 Payment Required` nếu vượt ngân sách user (hoặc `503` nếu vượt ngân sách hệ thống); sau khi LLM trả lời, `record_usage()` cộng dồn chi phí thực tế. Trong bản production (Part 6), tổng chi phí được lưu trong **Redis** (`INCRBYFLOAT` + TTL) để không mất khi restart và dùng chung giữa nhiều worker/instance.
- **Vì sao cần cả hai:** Rate limiting bảo vệ **tốc độ request và tính sẵn sàng** (số request/phút, chống spam/DDoS), trong khi Cost guard bảo vệ **chi phí/tiền** (tổng chi tiêu token tích luỹ theo ngày/tháng — chỉ vài request có prompt/output rất dài vẫn có thể lọt qua giới hạn RPM nhưng làm cạn ngân sách LLM).

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health checks & Graceful shutdown (`05-scaling-reliability/develop/app.py`)
- **Liveness probe (`GET /health`, dòng 104–145):** "Agent có còn sống không?". Trả về `200 OK` kèm uptime, checks và timestamp. Nếu endpoint này fail hoặc timeout, platform/orchestrator (Docker/K8s/Railway) sẽ tự động restart container.
- **Readiness probe (`GET /ready`, dòng 147–169):** "Agent có sẵn sàng nhận request chưa?". Trả về `200 OK` khi `_is_ready = True` và các dependency sẵn sàng; trả về `503 Service Unavailable` khi "Đang khởi động (model chưa load xong)", "Đang shutdown", hoặc khi database/dependencies chưa kết nối. Load balancer dựa vào đây để dừng route traffic vào instance đó mà không kill tiến trình.
- **Graceful shutdown (`SIGTERM`, dòng 41–67, 175–189):**
  - Xử lý qua `signal.signal(signal.SIGTERM, handle_sigterm)` và `lifespan`: đặt `_is_ready = False` để LB ngừng gửi request mới, sau đó chạy vòng lặp chờ (`while _in_flight_requests > 0`) tối đa 30s để các request đang xử lý hoàn thành trọn vẹn trước khi thoát với exit code 0.
- **Kết quả chạy thực tế:**
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

### Exercise 5.3, 5.4 & 5.5: Kiến trúc Stateless & test stateless (`05-scaling-reliability/production`)
- **Thiết kế Stateless:** Tránh anti-pattern "State trong memory" (vì mỗi instance có RAM riêng, dẫn đến hỏng/mất lịch sử khi scale nhiều instance hoặc restart). Toàn bộ session state và lịch sử hội thoại được lưu tập trung trong Redis (`redis:7-alpine`).
- **Load balancing:** Nginx phân phối round-robin các request tới 3 instance agent (`agent=3`) tại cổng `8080` (`POST /chat`).
- **Kết quả chạy `python test_stateless.py`:**
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
- **Giải thích:** 5 request liên tiếp được Nginx phân tán qua cả 3 instance khác nhau (`instance-a63de3`, `instance-50b377`, `instance-853938`), nhưng toàn bộ 10 message lịch sử hội thoại vẫn được truy xuất đầy đủ và nhất quán nhờ lưu trữ tập trung trong Redis.

---

## Part 6: Final Project (`06-lab-complete/`)

### Kết quả chạy `python check_production_ready.py`
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

---

## AI log
- **Công cụ sử dụng:** Trợ lý AI hỗ trợ hướng dẫn lệnh kiểm tra, cấu trúc các module Part 6 và tổng hợp số liệu Part 1–7.
- **Nội dung đã hỏi / nhận:**
  - Hỏi cách hoàn thiện các module `TODO` trong `06-lab-complete/` (`config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, multi-stage `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `railway.toml`, `render.yaml`) theo đúng hợp đồng chấm bài.
  - Nhận hướng dẫn xử lý `SIGTERM` (chaining `_previous_sigterm` trong `lifespan`), `ENV PYTHONUSERBASE` trong multi-stage Dockerfile cho non-root user, và cấu trúc sliding window bằng Redis sorted set (`ZREMRANGEBYSCORE`/`ZCARD`/`ZADD`/`EXPIRE`).
  - Nhận hỗ trợ viết lệnh chạy benchmark, eval, alert experiments và kiểm tra khớp số liệu từ các file report JSON/CSV.
- **Tự sửa & tự kiểm tra:**
  - Chạy trực tiếp toàn bộ ví dụ Part 1, 2, 4, 5 trong WSL2 (`posix`) và Docker Compose (`-p k5-day14-docker`, `-p k5-day14-scaling`).
  - Tự chạy `python check_production_ready.py` trong WSL2 và xác nhận đạt `PASS 12/12` (43/43 checks, image 69 MB).
  - Tự deploy agent Part 6 lên Render (`https://day14-ai-agent-0x1a.onrender.com`) kèm Render Key Value (Redis) và kiểm tra `/health` (200), `/ready` (200), `/ask` thiếu key (401), `/ask` có key (200).
  - Phát hiện và sửa lỗi `ModuleNotFoundError: uvicorn` trong `benchmark-observability/production/Dockerfile` do thiếu `ENV PYTHONUSERBASE=/home/agent/.local`, chạy toàn bộ load test, eval (`23/23` sau khi sửa KB), Locust scaling, Jaeger trace và 4 alert firing trên máy thật.
