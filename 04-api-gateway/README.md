# Section 4 — API Gateway & Security

## Mục tiêu học
- Hiểu tại sao cần lớp bảo vệ trước agent
- Implement API Key authentication
- Implement JWT authentication (nâng cao)
- Rate limiting và cost protection

---

## Ví dụ Basic — API Key Authentication

```
develop/
├── app.py              # Agent với API Key auth
└── requirements.txt
```

### Chạy thử
```bash
cd develop
pip install -r requirements.txt
AGENT_API_KEY=my-secret-key python app.py

# Test với key hợp lệ
curl -H "X-API-Key: my-secret-key" http://localhost:8000/ask \
     -X POST -H "Content-Type: application/json" \
     -d '{"question": "hello"}'

# Test không có key → 401
curl http://localhost:8000/ask -X POST \
     -H "Content-Type: application/json" \
     -d '{"question": "hello"}'
```

---

## Ví dụ Advanced — JWT + Rate Limiting + Cost Guard

```
production/
├── app.py              # Full security stack
├── auth.py             # JWT token logic
├── rate_limiter.py     # In-memory rate limiter
├── cost_guard.py       # Token budget và spending alerts
├── test_advanced.py    # Test suite
└── requirements.txt
```

### Chạy thử
```bash
cd production
pip install -r requirements.txt
python app.py

# Lấy JWT token
curl -X POST http://localhost:8000/auth/token \
     -H "Content-Type: application/json" \
     -d '{"username": "student", "password": "demo123"}'

# Dùng token
curl -H "Authorization: Bearer <token>" \
     http://localhost:8000/ask \
     -X POST -H "Content-Type: application/json" \
     -d '{"question": "what is docker?"}'

# Test rate limit: spam 20 requests liên tiếp
# Lấy token rồi gửi 20 requests — request 11+ sẽ bị chặn (429)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
     -H "Content-Type: application/json" \
     -d '{"username": "student", "password": "demo123"}' \
     | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

for i in $(seq 1 20); do
  printf "Request %2d: " $i
  curl -s -H "Authorization: Bearer $TOKEN" \
       -X POST http://localhost:8000/ask \
       -H "Content-Type: application/json" \
       -d '{"question": "what is docker?"}' \
       | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('answer','')[:60] if 'answer' in d else f'❌ {d.get(\"detail\",d)}')"
done
```

---

## Luồng bảo vệ

```
Request
  → Auth Check (401 nếu fail)
  → Rate Limit (429 nếu vượt quota)
  → Input Validation (422 nếu invalid)
  → Cost Check (402 nếu hết budget)
  → Agent (200 nếu mọi thứ OK)
```

---

## Câu hỏi thảo luận

1. Khi nào nên dùng API Key vs JWT vs OAuth2?
   - **Trả lời:** API Key phù hợp cho MVP, internal API, service-to-service đơn giản hoặc B2B integration. JWT phù hợp khi có user login, role, expiry, stateless authentication và cần phân quyền theo user. OAuth2 phù hợp khi cần đăng nhập qua bên thứ ba, delegated access, SSO/enterprise hoặc cấp quyền cho app khác truy cập thay user.

2. Rate limit nên đặt bao nhiêu request/phút cho một AI agent?
   - **Trả lời:** Mức khởi điểm hợp lý là khoảng `10 req/phút/user` cho user thường, và cao hơn cho admin/internal service, ví dụ `100 req/phút`. Tuy nhiên AI agent còn tốn tiền theo token, nên nên kết hợp rate limit với cost guard/token budget thay vì chỉ giới hạn số request.

3. Nếu API key bị lộ, bạn phát hiện và xử lý như thế nào?
   - **Trả lời:** Có thể phát hiện qua secret scanning, log bất thường, usage/cost tăng đột biến, request từ IP lạ hoặc cảnh báo từ provider. Cách xử lý: revoke key bị lộ ngay, rotate sang key mới, cập nhật environment variables trên server/cloud, redeploy, audit logs để xem bị dùng ở đâu, chặn abuse nếu cần, và xoá secret khỏi git history nếu từng commit lên repo public.
