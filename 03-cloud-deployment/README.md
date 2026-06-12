# Section 3 — Cloud Deployment Options

## 3 Tier: Chọn Platform Theo Nhu Cầu

| Tier | Platform | Khi nào dùng | Thời gian deploy |
|------|----------|-------------|-----------------|
| 1 | Railway, Render | MVP, demo, học | < 10 phút |
| 2 | AWS ECS, Cloud Run | Production | 15–30 phút |
| 3 | Kubernetes | Enterprise, large-scale | Vài giờ setup |

---

## railway/ — Deploy < 5 Phút

Không cần server config. Kết nối GitHub → Auto deploy.

```
railway/
├── railway.toml        # Railway config
├── Procfile            # Define start command
├── app.py              # Agent (Railway-ready)
└── requirements.txt
```

### Các bước deploy Railway:
1. `railway login` (hoặc qua browser)
2. `railway init`
3. `railway up`
4. Nhận URL dạng `https://your-app.up.railway.app`

---

## render/ — render.yaml (Infrastructure as Code)

Định nghĩa toàn bộ infrastructure trong 1 YAML file.

```
render/
├── render.yaml         # Khai báo service, env vars, disk
└── app.py
```

---

## production-cloud-run/ — GCP Cloud Run + CI/CD

Production-grade. Tự động build và deploy khi push code.

```
production-cloud-run/
├── cloudbuild.yaml     # CI/CD pipeline
├── service.yaml        # Cloud Run service definition
└── README.md           # Hướng dẫn chi tiết
```

---

## Câu hỏi thảo luận

1. Tại sao serverless (Lambda) không phải lúc nào cũng tốt cho AI agent?
   - **Trả lời:** AI agent thường có request lâu, streaming response, dependencies lớn, và đôi khi cần giữ kết nối hoặc chạy background task. Serverless như Lambda có timeout, cold start, giới hạn package/runtime và khó tối ưu cho workload cần phản hồi liên tục. Với agent production, container service như Cloud Run/ECS thường linh hoạt hơn.

2. "Cold start" là gì? Ảnh hưởng thế nào đến UX?
   - **Trả lời:** Cold start là thời gian platform cần để khởi tạo runtime/container mới trước khi xử lý request đầu tiên. Với AI agent, cold start làm user phải chờ lâu trước khi nhận phản hồi đầu tiên, khiến trải nghiệm chat/API bị chậm và kém mượt.

3. Khi nào nên upgrade từ Railway lên Cloud Run?
   - **Trả lời:** Nên upgrade khi app bước vào production thật: cần autoscaling tốt hơn, kiểm soát IAM/service account, logging/monitoring chặt chẽ, traffic splitting, custom container, VPC/private services, hoặc yêu cầu bảo mật và vận hành cao hơn. Railway rất hợp cho MVP/demo, còn Cloud Run hợp hơn cho production có traffic và SLA rõ ràng.
