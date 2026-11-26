# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Pham Ha Nam (MSSV: 2A202604023)
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11 + WSL2 (Ubuntu 22.04, Python 3.11.18), Docker Desktop, 16 vCPU / 7,528 MB RAM

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Baseline mock LLM + retrieval ~180–230ms ở tải vừa (`c=1..20`); ngưỡng 500ms bắt được tắc nghẽn queue hoặc tail latency tăng cao (`MOCK_SLOW_RATE=0.1`) mà vẫn dung nạp dao động jitter tự nhiên. |
| Error rate `/ask` | < 2.0 % | Upstream mock LLM có tỷ lệ lỗi nền `MOCK_ERROR_RATE=0.01` (1%); đặt SLO < 2% tránh báo giả do lỗi lẻ tẻ nhưng vẫn phát hiện ngay khi upstream suy giảm hoặc mất ổn định. |
| Accuracy trên golden dataset | ≥ 85 % | Đảm bảo chất lượng RAG đáp ứng hầu hết câu hỏi nghiệp vụ trên 23 câu golden dataset và chặn regression trong CI/CD (`.github/workflows/eval.yml` dùng `--min-accuracy 0.85`). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.50 | 196.1 | 219.9 | 1688.3 | 1.00% | PASS |
| 10 | 38.64 | 192.7 | 225.3 | 1699.8 | 0.33% | PASS |
| 50 | 47.46 | 309.8 | 2677.7 | 3421.2 | 1.67% | FAIL |
| 100 | 40.91 | 1200.3 | 5303.9 | 5832.7 | 1.00% | FAIL |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Không. Từ `c=1` lên `c=10`, RPS tăng gần tuyến tính (`4.50` → `38.64 req/s`) vì 1 process async xử lý tốt nhiều I/O wait song song mà p95 vẫn giữ ở ~225 ms. Tuy nhiên từ `c=50` lên `c=100`, RPS chạm trần và giảm nhẹ (`47.46` → `40.91 req/s`), trong khi p50 vọt từ `309.8 ms` lên `1200.3 ms` và p95 vọt lên `5303.9 ms` (FAIL SLO). Nguyên nhân là đơn tiến trình `uvicorn` + event loop và giới hạn kết nối/lập lịch trên 1 process bị bão hoà hàng đợi khi quá nhiều request đồng thời tranh chấp CPU/event-loop tick.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 192.7 | 224.2 | 250.4 |
| 0.03 (mặc định) | 215.0 | 229.7 | 1671.6 |
| 0.1 | 294.2 | 1677.9 | 1710.7 |

*(Chạy cùng `--requests 300 --concurrency 20` trên agent v2: `load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.)*

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

`p99` (và tiếp theo là `p95` khi tỷ lệ chậm vượt 5%) nhạy nhất với request chậm: khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03`, `avg` chỉ tăng nhẹ `+11.6%` (`192.7` → `215.0 ms`) trông vẫn "bình thường", nhưng `p99` tăng vọt `+567.6%` (`250.4` → `1671.6 ms`). Khi lên `0.1`, `p95` cũng nhảy lên `1677.9 ms` (`+648.4%`) trong khi `avg` mới là `294.2 ms`. Do đó SLO không nên đặt theo average vì trung bình cộng che giấu trải nghiệm tệ của nhóm user ở đuôi phân phối (tail latency).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 58.8 | 108.8 | 113.7 |
| Tổng cost (USD) | $0.000427 | $0.000757 | $0.000790 |
| Cost / câu đúng (USD) | $0.00042735 | $0.00003607 | $0.00003436 |
| Quality gate | FAIL | PASS (≥80%, 0 regression) | PASS (≥100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Bổ sung entry `(["jwt"], "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn; server xác minh chữ ký mà không cần tra database.")` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Bổ sung entry `(["hpa", "kubernetes", "autoscal"], "Kubernetes HPA (Horizontal Pod Autoscaler) scale số pod dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi.")` vào `KNOWLEDGE_BASE`. |

**CI Quality Gate (Exercise 7.3):** Đã thêm workflow `.github/workflows/eval.yml` chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85` trên mỗi `pull_request`. `run_eval.py` trả về **exit code 1** nếu accuracy < `--min-accuracy` hoặc có bất kỳ câu nào bị regression so với baseline, khiến GitHub Actions fail job và chặn merge PR.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

`v2` bổ sung bước retrieval (`search_knowledge_base`, thêm ~20ms) và nhồi context vào prompt khiến `avg tokens/câu` tăng gần gấp đôi (`58.8` → `113.7`) và tổng chi phí bộ eval tăng (`$0.000427` → `$0.000790`), nhưng accuracy tăng vọt từ `4.3%` lên `100.0%`. Nhờ vậy **cost / câu đúng** của `v2` (`$0.00003436`) rẻ hơn **~12.4 lần** so với `v1` (`$0.00042735`). Đây là minh chứng cho thấy "cost / câu đúng" phản ánh hiệu quả kinh tế thực chất hơn "cost / câu".

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — [grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`) — [jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing** — [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Trả lời Exercise 7.4 (quan sát stack với Locust 30 users):**
1. **p95 vs avg trên Prometheus/Grafana:** `avg ≈ 207.1 ms`, `p95 ≈ 199.4 ms` (khi chạy không tải đột biến; lúc có tail latency ~3%, `p99` vọt lên > 1.6s trong khi `avg` chỉ nhích nhẹ, thể hiện rõ phần đuôi phân phối trên panel Latency).
2. **Nginx load balancing (`rps_by_instance`):** Có — `172.22.0.4:8000` (`9.26 req/s`) và `172.22.0.8:8000` (`9.47 req/s`), gần như 50/50 theo round-robin; header `X-Served-By` luân phiên giữa 2 instance.
3. **Vì sao `input tokens/s` (`674.85`) lớn hơn `output tokens/s` (`368.46`):** Mỗi request gửi kèm `SYSTEM_PROMPT`, context RAG được retrieve và câu hỏi của user ở phần input, còn câu trả lời của agent ngắn gọn hơn nhiều.
4. **`curl http://localhost:8080/metrics`:** Trả về `404 Not Found` vì `nginx/nginx.conf` chặn endpoint `/metrics` từ bên ngoài; chỉ Prometheus trong mạng nội bộ Docker (`obs_net`) mới scrape được `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`) | ~78s | Golden Signals — Error rate (đỏ >5%) & LLM calls ok/error |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`) | ~128s | Golden Signals — p95 & Latency/Traffic (`p95`/`p99`) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`) | ~157s | Cost 1h & Cost USD/giờ (tăng mạnh do giá model large gấp ~16.7x) |
| D | `docker pause` 1 instance (`566fb3dd1eb1`) | `AgentInstanceDown` (`for: 30s`) | ~41s (pause tại `97s`, firing tại `138s`) | Golden Signals — Instances up (giảm từ 2 xuống 1) & req/s theo instance |
| E | `AGENT_VERSION=v1` | Không có alert mới firing (hạ tầng xanh) | N/A | Retrieval hit ratio tụt về 0%, tokens/s giảm, bảng `agent_info` đổi sang `v1` |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Cần kết hợp đánh giá chất lượng tự động và tín hiệu người dùng ngoài metric hạ tầng:
1. Chạy **CI eval quality gate** (`eval/run_eval.py` trên golden dataset) trước mỗi lần deploy để chặn phiên bản làm tụt accuracy (ví dụ `v1` đạt 4.3% < 85%).
2. Theo dõi **metric đặc thù của RAG/Agent** như retrieval hit ratio (đã giảm về 0% ở `v1`) và thiết lập alert khi tỷ lệ retrieval rỗng tăng bất thường.
3. Chạy **online eval / LLM-as-judge** lấy mẫu một phần traffic production và thu thập feedback người dùng (thumbs up/down, tỷ lệ hỏi lại).

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: `2540ef4e568377994608b98597c9335b`
- Tổng thời gian: `3687.82 ms` (trên Jaeger; log `http_request` ghi nhận `3675.9 ms`)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`3639.71 ms`, **98.7%** tổng thời gian; trong khi `agent.retrieve_context` chỉ mất `25.18 ms`)
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-26T10:18:24.656601+00:00", "level": "INFO", "service": "observable-agent", "instance": "8193435a9a43", "event": "http_request", "trace_id": "2540ef4e568377994608b98597c9335b", "span_id": "09ee58466157e4b0", "request_id": "7f7b90c8bd34", "method": "POST", "route": "/ask", "status": 200, "ms": 3675.9}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Số liệu lấy từ `POST /ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`; Aggregated lần lượt là 66.84 RPS và 65.68 RPS.)*

| Số instance | RPS (`/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures (`/ask`) |
|---|---|---|---|---|---|
| 1 | 60.62 | 200 | 390 | 1700 | 59 / 7051 (0.84%) |
| 3 | 59.88 | 210 | 570 | 1800 | 75 / 6962 (1.08%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Scale từ 1 lên 3 instance **không** cải thiện RPS (~60 req/s) hay p95 (390 ms → 570 ms). Nguyên nhân là nút thắt không nằm ở CPU của agent mà nằm ở **I/O latency của upstream LLM call** (~120–180ms + 20ms retrieval + 3% tail latency +1500ms): FastAPI/Uvicorn chạy bất đồng bộ (`asyncio`) nên ngay cả 1 instance đã đủ gánh 100 user đồng thời chờ I/O mà chưa bão hoà CPU. Khi chạy 3 instance trên cùng 1 máy host (cùng Nginx, Locust, Prometheus, Grafana, Jaeger), thêm container làm tăng chi phí context-switch và proxy qua Nginx khiến p95 nhích lên nhẹ.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Average che giấu tail latency:** SLO cần đặt theo `p95`/`p99` vì chỉ 3% request chậm đã đẩy `p99` lên gấp 6–7 lần trong khi `avg` gần như không đổi.
  2. **Metric hạ tầng xanh không đồng nghĩa agent đúng:** Chuyển về `v1` không kích hoạt alert hạ tầng nào; bắt buộc phải có `eval` trên golden dataset + quality gate để kiểm soát chất lượng và tối ưu `cost / câu đúng`.
  3. **3 trụ cột Logs – Metrics – Traces bổ trợ nhau:** Metrics/Alerts báo *khi nào* có vấn đề, Tracing (Jaeger) chỉ ra *span nào* gây chậm/lỗi (`chat mock-llm-small` chiếm 98.7%), và `trace_id` nối thẳng sang JSON logs để debug chi tiết.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Alert khi **retrieval hit ratio** giảm đột ngột (phát hiện lỗi vector DB hoặc suy giảm chất lượng RAG sớm).
  - Giám sát và alert **5xx / 504 tại tầng Nginx/Load Balancer** (vì request timeout ở proxy không đi tới metric nội bộ của agent).
  - Alert **rate limit (429 rate) & budget utilization** theo từng tenant/API key, cùng chỉ số **online quality score** (LLM-as-judge / user feedback rate).
