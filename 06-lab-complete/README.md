# Lab 12 - Day09 Multi-Agent Production App

This folder is ready to deploy a production FastAPI wrapper for the Day09 shopping assistant.

The public UI at `/` lets users run a simple multi-agent demo:

User question -> Supervisor -> Policy Worker and/or Data Worker -> Response Worker

The demo reads the real Day09 lab files:

- `Day09-MultiAgent-Architecture/data/policy_mock_vi.md`
- `Day09-MultiAgent-Architecture/data/order_customer_mock_data.json`

## Endpoints

- `GET /` - browser UX for the Day09 flow
- `POST /demo/ask` - public demo endpoint used by the UX
- `POST /ask` - protected API endpoint, requires `X-API-Key`
- `GET /health` - liveness probe
- `GET /ready` - readiness probe
- `GET /metrics` - protected operational metrics

## Run Local

```bash
cp .env.example .env.local
docker compose up --build
```

Open:

```text
http://localhost:8000
```

Protected API example:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-a-long-random-key" \
  -d "{\"question\":\"Don hang 1971 co duoc hoan tra khong?\"}"
```

## Deploy Railway

From `06-lab-complete`:

```bash
railway login
railway init
railway variables set ENVIRONMENT=production
railway variables set APP_NAME="Day09 Multi-Agent Shopping Assistant"
railway variables set LLM_MODEL=day09-demo
railway variables set AGENT_API_KEY="your-long-random-key"
railway variables set JWT_SECRET="your-long-random-secret"
railway up
railway domain
```

Railway uses `railway.toml`, Dockerfile, and the `/health` check.

## Production Readiness

```bash
python check_production_ready.py
```

All checklist items should pass before deploy.
