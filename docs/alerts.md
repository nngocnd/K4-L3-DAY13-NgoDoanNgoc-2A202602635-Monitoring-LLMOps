# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

Rule máy đọc được nằm trong [`../config/alert_rules.yaml`](../config/alert_rules.yaml); nguồn dữ liệu là `data/logs.jsonl`, dashboard dựng bằng `python scripts/build_dashboard.py`.

## Alert 1

- Tên: `slow_responses_p95_slo_breach`
- Severity: P2
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-oncall`
- SLI/SLO liên quan: `fast_successful_requests` — 99.5% request có `response_sent` với `latency_ms <= 3000` trong 28 ngày (panel **Latency percentiles and TTFT**).
- Điều kiện và thời gian duy trì: P95 `latency_ms` của `response_sent` trong cửa sổ 5 phút > 3000 ms, kéo dài liên tục 5 phút.
- Ảnh hưởng tới người dùng: câu trả lời chậm rõ rệt; request chậm tính là bad event nên tiêu error budget (0.5%).
- Ba bước kiểm tra đầu tiên:
  1. Trên dashboard, so P95 với TTFT P95: TTFT vẫn ~50 ms mà latency tăng → chậm nằm ngoài bước sinh token đầu (retrieval, prompt fetch hoặc hàng đợi).
  2. Lọc log `response_sent` có `latency_ms > 3000`, lấy `correlation_id`.
  3. Mở trace có cùng `correlation_id` trong Langfuse, xem waterfall: span `retrieval`, `prompt-resolve` hay `llm-generation` chiếm thời gian.
- Mitigation tạm thời: nếu `retrieval` chậm → tắt nguồn chậm/dùng fallback docs hoặc cache; nếu `prompt-resolve` chậm → dựa vào cache prompt/fallback local; nếu chỉ tăng ở client mà span nhanh → giảm concurrency (handler async đang gọi code blocking).
- Owner: ngo-doan-ngoc (on-call LLMOps)

## Alert 2

- Tên: `high_error_rate`
- Severity: P1
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-oncall`
- SLI/SLO liên quan: `fast_successful_requests` (request lỗi không có `response_sent` nên là bad event) và guardrail `error_rate_pct_max: 2`, `retrieval_success_rate_pct_min: 90` (panel **Error rate and retrieval success**).
- Điều kiện và thời gian duy trì: `count(request_failed) / count(request_received) * 100` trong cửa sổ 5 phút > 2%, kéo dài 5 phút.
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500, không có câu trả lời; tiêu error budget rất nhanh.
- Ba bước kiểm tra đầu tiên:
  1. Xem breakdown `error_type` và retrieval success trên dashboard: lỗi tập trung một loại hay nhiều loại?
  2. Lọc log `request_failed` (field `error_type`, `tool_name`, `tool_success=false`, `payload.detail`) để lấy `correlation_id`.
  3. Mở trace tương ứng: span `retrieval` có `level=ERROR` và `status_message` → lỗi ở vector store; nếu retrieval OK → xem `llm-generation`.
- Mitigation tạm thời: nếu lỗi retrieval (ví dụ `Vector store timeout`) → trả lời fallback không dùng docs hoặc chuyển vector store dự phòng; nếu do prompt/release mới → rollback label `production` của prompt `day13-chat` về version trước.
- Owner: ngo-doan-ngoc (on-call LLMOps)

## Alert 3

- Tên: `cost_burn_above_daily_budget_pace`
- Severity: P3
- Duration: 15m
- Kênh thông báo: Slack `#day13-llmops-cost`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5` (panel **Cost over time** và **Input and output tokens**).
- Điều kiện và thời gian duy trì: tổng `cost_usd` trong 1 giờ gần nhất > 0.21 USD (gấp 2 nhịp chi 2.5 USD/ngày ≈ 0.104 USD/giờ), kéo dài 15 phút.
- Ảnh hưởng tới người dùng: chưa ảnh hưởng trực tiếp, nhưng nếu giữ nhịp này ngân sách ngày cạn trong < 12 giờ và dịch vụ có thể bị giới hạn.
- Ba bước kiểm tra đầu tiên:
  1. Panel tokens: `tokens_out` tăng bất thường (câu trả lời dài hơn) hay `tokens_in` tăng (prompt/docs dài hơn) hay chỉ traffic tăng?
  2. Lọc log `response_sent` có `cost_usd` cao nhất, so `prompt_version` trong trace tương ứng với version production hiện tại.
  3. Mở generation `llm-generation` trong Langfuse: kiểm tra `usage_details`, `cost_details`, model và prompt version.
- Mitigation tạm thời: rollback prompt nếu version mới làm câu trả lời dài; giới hạn `max_tokens` output; rate limit theo `user_id_hash`/feature nếu traffic tăng bất thường.
- Owner: ngo-doan-ngoc (LLMOps cost owner)
