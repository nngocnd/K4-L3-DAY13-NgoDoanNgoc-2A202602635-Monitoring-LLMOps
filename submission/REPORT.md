# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Ngọ Doãn Ngọc
- **MSSV:** 2A202602635
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/nngocnd/K4-L3-DAY13-NgoDoanNgoc-2A202602635-Monitoring-LLMOps
- **Commit SHA cuối:** 
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602635`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.txt` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | Đạt toàn bộ tiêu chí (schema, correlation ID, enrichment, PII) |
| `validate_dashboard.py` | | HỢP LỆ: 6/6 panel | Contract giữ nguyên; dashboard runtime render bằng `scripts/build_dashboard.py` |
| `pytest` | 22 passed | 26 passed | Bổ sung test PII (CCCD, credit card), test chat observability và test child observations retrieval/generation |
| Số traces hợp lệ | | 80 | Trace `day13-agent-request` trong project cá nhân, đều có root `lab-agent-run` + `retrieval` + `llm-generation` |
| Số PII leak | 0 | 0 | Không còn PII nguyên văn trong logs; trace chỉ chứa preview đã scrub (`[REDACTED_EMAIL]`, …) |
| Latency P95 / TTFT P95 | | 2654 ms / 51 ms | Cửa sổ 60 phút gồm một lượt thử `rag_slow`; request bình thường ~153 ms |
| Retrieval success rate | | 100% | 0 `request_failed` trong cửa sổ 60 phút |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` xóa context cũ (`clear_contextvars()`), trích xuất header `x-request-id` nếu có hoặc sinh mới theo format `req-<8-hex>` (`f"req-{uuid.uuid4().hex[:8]}"`). ID này được bind vào contextvars (`bind_contextvars(correlation_id=...)`), lưu vào `request.state.correlation_id` và đính kèm vào response headers (`x-request-id` và `x-response-time-ms`).
- **Các metadata được ghi vào structured log:** Tại endpoint `/chat`, log được làm giàu qua `bind_contextvars` với `user_id_hash` (băm SHA-256 cắt 12 ký tự), `session_id`, `feature`, `model` (`agent.model`), và `env` (`os.getenv("APP_ENV", "dev")`) trước khi bắn log `request_received`.
- **Cách bảo đảm PII được scrub trước khi ghi:** Đăng ký processor `scrub_event` trong structlog processors nằm **trước** `JsonlFileProcessor` và `JSONRenderer`. Processor này duyệt đệ quy các trường trong `payload` và `event`, áp dụng `scrub_text` để che Email, SĐT Việt Nam, CCCD, và Thẻ thanh toán thành `[REDACTED_*]` trước khi log được ghi file hoặc in ra stdout.
- **Cách kiểm chứng kết quả:** Chạy `scripts/load_test.py` sau khi xóa log cũ, kiểm tra response headers có correlation ID hợp lệ, chạy `python scripts/validate_logs.py` đạt điểm tuyệt đối 100/100 và chạy bộ unit test `pytest` (25/25 test cases passed).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** `.env` dùng key của project `day13-k4-l3a-2A202602635` (`auth_check()` = True). Tôi tự gửi request với `x-request-id` cố định (`req-ba5e0011`, `req-cad00012`, `req-9d0d0021..23`) rồi đọc lại qua `GET /api/public/v2/observations` và thấy đúng `correlation_id` trong metadata trace. Tổng cộng 80 trace sau `load_test.py --concurrency 5`.
- **Cấu trúc root/retrieval/generation observations:** root `lab-agent-run` (agent, `@observe`) → con `retrieval` (retriever: input `query_preview` đã scrub, output `doc_count`, `level=ERROR` khi retrieval lỗi) → `prompt-resolve` (span bao lần fetch prompt Langfuse; cold fetch ~1 s) → `llm-generation` (generation: `model`, prompt managed được link, `usage_details` input/output, `cost_details` input/output/total, `ttft_ms`). Trace có `user_id` đã hash SHA-256 (12 ký tự), `session_id`, `environment`, tags, và metadata `feature`, `model`, `correlation_id`. `capture_input/output=False` ở root; con chỉ ghi preview qua `summarize_text()` nên không có PII thô.
- **Cách nối trace với log:** cùng `correlation_id` (`req-<8-hex>`) nằm trong log JSONL và metadata trace. Lọc log → lấy `correlation_id` → tìm trace có metadata đó.
- **Prompt name:** `day13-chat` (text prompt, biến `{{feature}}`, `{{docs}}`, `{{message}}`).
- **Version/label baseline:** version 1, labels `baseline`, `production` (template starter).
- **Version/label candidate:** version 2, label `candidate` — thêm dòng `Answer in at most 3 concise bullet points.` (tokens_in tăng 32 → 43 với cùng input).
- **Trace ID của mỗi version:** cùng input `"Explain why metrics traces and logs work together"`:
  - `baseline` → v1: trace `cc75b334e7fee26c8afdd4077253ed01` (`req-ba5e0011`)
  - `candidate` → v2: trace `210a204278e1e75ec810a381cbd783e4` (`req-cad00012`)
  - `production` sau promote → v2: trace `9975d711abe73d3e7182001ca56b88ac` (`req-9d0d0022`)
  - `production` sau rollback → v1: trace `eaf7a5f8adcb45d108274cf7a9ff44ec` (`req-9d0d0023`)
- **Cách promote và rollback `production`:** `update_prompt(name="day13-chat", version=2, new_labels=["candidate","production"])` để promote (label `production` chuyển khỏi v1), chạy lại request thấy `prompt_version=2`; rollback bằng `update_prompt(..., version=1, new_labels=["baseline","production"])`, request tiếp theo thấy `prompt_version=1`. App không cần deploy lại vì prompt được fetch theo label (cache 60 s).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `python scripts/build_dashboard.py` đọc `config/dashboard.yaml` (contract, threshold) và `data/logs.jsonl`, render 6 panel ra `evidence/11-dashboard-overview.png` (`--watch` render lại mỗi 30 s). Mỗi panel có tên, đơn vị, time range 60 phút và đường SLO/threshold: Latency P50/P95/P99 + TTFT P95 (≤ 3000 ms); Traffic req/phút (≥ 1); Error rate + breakdown `error_type` + retrieval success (≤ 2%); Cost theo phút + lũy kế (≤ 2.5 USD); tokens in/out lũy kế (≤ 50 000); Quality mean (≥ 0.75). Snapshot: P50 153 / P95 2654 / P99 2662 ms, TTFT P95 51 ms, 78 request, error 0%, retrieval 100%, cost 0.1629 USD, tokens 2 644 / 10 328, quality 0.872. Lượt thử `rag_slow` làm P95 phút đó tăng từ ~1 160 ms lên 2 654 ms, đúng hướng mong đợi.
- **SLO và lý do chọn:** giữ `fast_successful_requests`: 99.5% request có `response_sent` với `latency_ms ≤ 3000` trong 28 ngày. Baseline bình thường ~150 ms, cold prompt fetch ~1.1–1.5 s, `rag_slow` ~2.65 s → 3000 ms chừa headroom cho cold start và một sự cố retrieval nhẹ, nhưng bắt được khi retrieval chậm hơn hoặc request bị xếp hàng. Request lỗi không có `response_sent` nên tự động là bad event.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5% số request. Ví dụ 10 req/phút trong 28 ngày = 403 200 request → cho phép 2 016 request chậm/lỗi. Cửa sổ baseline: 78 request, 0 bad → tiêu 0% budget (chỉ được phép 0.39 request, nên ở lưu lượng lab một request xấu đã vượt budget của cửa sổ — vì vậy alert dùng tỷ lệ/percentile theo cửa sổ 5 phút thay vì đếm tuyệt đối). Burn rate = tỷ lệ bad / 0.005.
- **Ba alert và runbook tương ứng:** trong `config/alert_rules.yaml` và `docs/alerts.md`: (1) `slow_responses_p95_slo_breach` — P2, P95 > 3000 ms trong 5 phút, `#day13-llmops-oncall`; (2) `high_error_rate` — P1, error rate > 2% trong 5 phút, `#day13-llmops-oncall`; (3) `cost_burn_above_daily_budget_pace` — P3, cost 1 giờ > 0.21 USD (2× nhịp 2.5 USD/ngày) kéo dài 15 phút, `#day13-llmops-cost`. Mỗi alert có owner, runbook với ba bước kiểm tra (dashboard → log `correlation_id` → trace waterfall) và mitigation.
- **Quan sát thêm:** khi `rag_slow`, latency phía client ~13 s dù `latency_ms` server chỉ ~2.65 s, vì handler `async def chat` gọi code blocking (`time.sleep`) nên request bị xếp hàng trên event loop. SLO đo phía server sẽ bỏ sót phần chờ này.

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4, feature bị ảnh hưởng `monitoring`, ngưỡng challenge 2000 ms).
- **Khoảng thời gian điều tra:** 2026-09-29 10:22:11–10:23:06 UTC. Baseline (chưa inject) 10:22:11–10:22:21; inject `python scripts/inject_incident.py` lúc 10:22:51; `load_test.py --challenge --concurrency 5` 10:22:51–10:23:05.
- **Triệu chứng từ metrics:** panel **Latency percentiles and TTFT** (`evidence/12-incident-metric.png`): phút 10:23 UTC P50 = P95 = **2652 ms**, vượt ngưỡng challenge 2000 ms (5/5 request, 100%), trong khi request warm ở baseline chỉ 152 ms (tăng ~17×). **TTFT P95 giữ nguyên 50 ms**, error rate 0%, retrieval success 100%, tokens/cost/quality không đổi → chậm nằm trước bước LLM, không phải lỗi. Lưu ý: điểm P95/P99 5671 ms ở phút 10:22 là request cold-start của baseline (xem hạn chế bên dưới), không phải incident.
- **Log line và correlation ID liên quan:** `correlation_id = req-965ab70c` (`evidence/13-incident-log.txt`):
  `{"event": "response_sent", "latency_ms": 2652, "ttft_ms": 50, "tokens_in": 36, "tokens_out": 128, "tool_name": "retrieval", "tool_success": true, "feature": "monitoring", "session_id": "k4-l3a-challenge-s04", "correlation_id": "req-965ab70c", "ts": "2026-09-29T10:22:57.655242Z", ...}`. Cả 5 dòng `response_sent` sau `incident_enabled` (payload `rag_slow`, 10:22:51) đều có `latency_ms` 2652–2654.
- **Trace ID và span gây ảnh hưởng:** trace `5c2b913a8da11bca354d823b5f7d471a` (metadata `correlation_id=req-965ab70c`): root `lab-agent-run` 2.654 s, trong đó span **`retrieval` 2.500 s (~94%)**, `prompt-resolve` 0 s, `llm-generation` ~0.15 s. So với trace baseline warm `7b0b6d769e67596021b14a2d88e5beb0` (`req-cff948e4`): root 0.152 s, `retrieval` 0 s. Cả 5 trace incident đều có `retrieval` ≈ 2.50 s; không span nào có `level=ERROR`.
- **Root cause:** bước retrieval (vector store / `app/mock_rag.retrieve`) bị chậm thêm cố định ~2.5 s mỗi request (incident `rag_slow`). Metric (latency tăng, TTFT không đổi), log (`latency_ms` 2652 với `tool_success=true`) và trace (span `retrieval` 2.5 s) cùng chỉ về một nguyên nhân: retrieval chậm, không phải LLM, prompt hay lỗi.
- **Fix action:** tắt nguồn gây chậm (`python scripts/inject_incident.py --disable` → `rag_slow: false`); trong hệ thống thật: đặt timeout cho retrieval (ví dụ 500 ms) và trả lời bằng fallback docs/cache khi quá hạn, hoặc chuyển sang replica vector store khỏe.
- **Preventive measure:** alert `slow_responses_p95_slo_breach` (P95 > 3000 ms trong 5 phút) cộng thêm alert/panel riêng cho duration span `retrieval` (P95 > 500 ms) để bắt sớm trước khi vượt SLO; cache kết quả retrieval cho câu hỏi lặp; timeout + circuit breaker quanh retrieval; chuyển handler `/chat` sang `def` (threadpool) hoặc dùng I/O async để một dependency chậm không làm request xếp hàng — phía client đo được ~13 s dù server chỉ 2.65 s.
- **Phát hiện phụ (không phải root cause của challenge):** request đầu tiên sau khi khởi động (`req-472a4196`, trace `b72cb98ebf5d08d9beab147277291964`) mất 5671 ms, gần hết nằm ở span `prompt-resolve` 5.5 s và kết thúc bằng `prompt_source=local-fallback` — cold start của Langfuse client/prompt fetch. Nên warm-up prompt cache lúc startup.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
