# Section 1 — Từ Localhost Đến Production

## Mục tiêu học
- Hiểu tại sao "it works on my machine" là vấn đề
- Nhận ra sự khác biệt giữa dev và production environment
- Áp dụng 4 nguyên tắc 12-factor cơ bản

---

## Ví dụ Basic — Agent "Kiểu Localhost"

```
develop/
├── app.py          # ❌ Anti-patterns: hardcode secrets, no config, no health check
└── requirements.txt
```

### Chạy thử
```bash
cd develop
pip install -r requirements.txt
python app.py
# Truy cập: http://localhost:8000
```

### Những vấn đề trong code này:
1. API key hardcode trong code
2. Không có health check endpoint
3. Debug mode bật cứng
4. Không xử lý SIGTERM gracefully
5. Config không đến từ environment

---

## Ví dụ Advanced — 12-Factor Compliant Agent

```
production/
├── app.py          # ✅ Clean: config from env, health check, graceful shutdown
├── config.py       # ✅ Centralized config management
├── .env.example    # ✅ Template — không commit .env thật
└── requirements.txt
```

### Chạy thử
```bash
cd production
pip install -r requirements.txt
cp .env.example .env
# Sửa .env nếu cần
python app.py
```

### So sánh với Basic:

| | Basic (❌) | Advanced (✅) |
|--|-----------|--------------|
| Config | Hardcode trong code | Đọc từ env vars |
| Secrets | `api_key = "sk-abc123"` | `os.getenv("OPENAI_API_KEY")` |
| Port | Cố định `8000` | Từ `PORT` env var |
| Health check | Không có | `GET /health` |
| Shutdown | Tắt đột ngột | Graceful — hoàn thành request hiện tại |
| Logging | `print()` | Structured JSON logging |

---

## Câu hỏi thảo luận

1. Điều gì xảy ra nếu bạn push code với API key hardcode lên GitHub public?
   - **Trả lời:** API key có thể bị bot hoặc người khác quét được và dùng trái phép. Hậu quả là rò rỉ quyền truy cập, phát sinh chi phí, hoặc bị gọi API để spam/abuse. Khi lỡ commit key, cần revoke/rotate key ngay, tạo key mới qua environment variables, kiểm tra logs/usage, và xoá secret khỏi git history nếu repo public.

2. Tại sao stateless quan trọng khi scale?
   - **Trả lời:** Khi scale nhiều instances, load balancer có thể gửi mỗi request đến một instance khác nhau. Nếu state lưu trong memory của từng instance, user sẽ mất session/conversation khi request chuyển instance hoặc container restart. Stateless design giúp mọi instance xử lý request như nhau vì state được lưu ở Redis/DB/shared storage.

3. 12-factor nói "dev/prod parity" — nghĩa là gì trong thực tế?
   - **Trả lời:** Nghĩa là môi trường development, staging và production nên giống nhau nhất có thể: cùng runtime version, dependency version, cách config bằng environment variables, service phụ trợ tương tự, và quy trình deploy gần giống production. Mục tiêu là giảm lỗi kiểu "chạy trên máy em được nhưng lên production thì fail".
