from __future__ import annotations

import json
import logging
import signal
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings
from app.day09_demo import Day09DemoAgent


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "lvl": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            },
            ensure_ascii=False,
        )


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    handlers=[_handler],
    force=True,
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0
_daily_cost = 0.0
_cost_reset_day = time.strftime("%Y-%m-%d")
_rate_windows: dict[str, deque] = defaultdict(deque)
_agent: Day09DemoAgent | None = None


def log_event(event: str, **payload: object) -> None:
    logger.info(json.dumps({"event": event, **payload}, ensure_ascii=False))


def check_rate_limit(key: str) -> None:
    now = time.time()
    window = _rate_windows[key]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min",
            headers={"Retry-After": "60"},
        )
    window.append(now)


def check_and_record_cost(input_tokens: int, output_tokens: int) -> None:
    global _daily_cost, _cost_reset_day
    today = time.strftime("%Y-%m-%d")
    if today != _cost_reset_day:
        _daily_cost = 0.0
        _cost_reset_day = today
    if _daily_cost >= settings.daily_budget_usd:
        raise HTTPException(503, "Daily budget exhausted. Try tomorrow.")
    estimated_cost = (input_tokens / 1000) * 0.00015 + (output_tokens / 1000) * 0.0006
    _daily_cost += estimated_cost


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key or api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
        )
    return api_key


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _agent, _is_ready
    log_event(
        "startup",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
    _agent = Day09DemoAgent()
    _is_ready = True
    log_event("ready", data_source="Day09-MultiAgent-Architecture")
    yield
    _is_ready = False
    log_event("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    started = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if "server" in response.headers:
            del response.headers["server"]
        log_event(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.time() - started) * 1000, 1),
        )
        return response
    except Exception:
        _error_count += 1
        log_event("request_error", path=request.url.path)
        raise


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class AgentResponse(BaseModel):
    question: str
    answer: str
    route: dict
    policy_result: dict | None
    data_result: dict | None
    trace: list[dict]
    model: str
    timestamp: str


def _get_agent() -> Day09DemoAgent:
    if _agent is None:
        raise HTTPException(503, "Agent is not ready")
    return _agent


def _run_agent(question: str) -> dict:
    agent = _get_agent()
    input_tokens = len(question.split()) * 2
    check_and_record_cost(input_tokens, 0)
    result = agent.ask(question)
    output_tokens = len(result["final_answer"].split()) * 2
    check_and_record_cost(0, output_tokens)
    return result


@app.get("/", response_class=HTMLResponse, tags=["UX"])
def home() -> str:
    return HTML_PAGE


@app.get("/api/samples", tags=["UX"])
def samples() -> dict:
    return {"samples": _get_agent().samples()}


@app.post("/demo/ask", response_model=AgentResponse, tags=["UX"])
async def ask_demo(body: AskRequest, request: Request):
    client = request.client.host if request.client else "anonymous"
    check_rate_limit(f"demo:{client}")
    log_event("demo_agent_call", q_len=len(body.question), client=client)
    result = _run_agent(body.question)
    return AgentResponse(
        question=body.question,
        answer=result["final_answer"],
        route=result["route"],
        policy_result=result["policy_result"],
        data_result=result["data_result"],
        trace=result["trace"],
        model=settings.llm_model,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/ask", response_model=AgentResponse, tags=["Agent"])
async def ask_agent(
    body: AskRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    check_rate_limit(f"key:{_key[:8]}")
    log_event(
        "agent_call",
        q_len=len(body.question),
        client=request.client.host if request.client else "unknown",
    )
    result = _run_agent(body.question)
    return AgentResponse(
        question=body.question,
        answer=result["final_answer"],
        route=result["route"],
        policy_result=result["policy_result"],
        data_result=result["data_result"],
        trace=result["trace"],
        model=settings.llm_model,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health", tags=["Operations"])
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "checks": {
            "day09_data": "loaded" if _agent else "starting",
            "agent_mode": "day09_demo",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    if not _is_ready:
        raise HTTPException(503, "Not ready")
    return {"ready": True}


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "daily_cost_usd": round(_daily_cost, 4),
        "daily_budget_usd": settings.daily_budget_usd,
        "budget_used_pct": round(_daily_cost / settings.daily_budget_usd * 100, 1),
    }


def _handle_signal(signum, _frame):
    log_event("signal", signum=signum)


signal.signal(signal.SIGTERM, _handle_signal)


HTML_PAGE = r"""
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Day09 Multi-Agent Shopping Assistant</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #18202a;
      --muted: #5c6675;
      --line: #d8dee8;
      --panel: #ffffff;
      --bg: #f4f6f8;
      --green: #1f8a5b;
      --red: #c74343;
      --blue: #286fb7;
      --amber: #a76b00;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 750;
      letter-spacing: 0;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--green);
    }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 460px) 1fr;
      gap: 18px;
      padding: 18px;
      max-width: 1280px;
      margin: 0 auto;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
    }
    .composer {
      padding: 16px;
      display: grid;
      gap: 12px;
    }
    label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }
    textarea {
      width: 100%;
      min-height: 150px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      font: inherit;
      line-height: 1.45;
      color: var(--ink);
      background: #fbfcfd;
    }
    button {
      min-height: 40px;
      border: 1px solid var(--blue);
      border-radius: 8px;
      background: var(--blue);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled {
      opacity: .6;
      cursor: wait;
    }
    .samples {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .sample {
      border-color: var(--line);
      background: #f7fafc;
      color: var(--ink);
      min-height: 34px;
      padding: 0 10px;
      font-size: 13px;
      font-weight: 650;
    }
    .results {
      display: grid;
      grid-template-rows: auto auto 1fr;
      min-height: calc(100vh - 96px);
    }
    .summary {
      padding: 16px;
      border-bottom: 1px solid var(--line);
      display: grid;
      gap: 10px;
    }
    .answer {
      white-space: pre-wrap;
      line-height: 1.55;
      margin: 0;
    }
    .route {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 30px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fbfcfd;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }
    .pill.on { color: var(--green); border-color: #9ed4b9; background: #f0fbf5; }
    .pill.warn { color: var(--amber); border-color: #e8ca8d; background: #fff9eb; }
    .trace {
      padding: 16px;
      display: grid;
      gap: 10px;
      align-content: start;
    }
    .node {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      display: grid;
      gap: 8px;
      background: #ffffff;
    }
    .node-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-weight: 750;
    }
    .node pre {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .empty {
      color: var(--muted);
    }
    .error {
      color: var(--red);
      font-weight: 700;
    }
    @media (max-width: 840px) {
      header { align-items: flex-start; flex-direction: column; }
      main { grid-template-columns: 1fr; }
      .results { min-height: 520px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Day09 Multi-Agent Shopping Assistant</h1>
    <div class="status"><span class="dot"></span><span>Railway-ready FastAPI demo</span></div>
  </header>
  <main>
    <section class="composer">
      <label for="question">Cau hoi khach hang</label>
      <textarea id="question">Don hang 1971 co duoc hoan tra khong?</textarea>
      <button id="run" type="button">Run multi-agent flow</button>
      <label>Vi du nhanh</label>
      <div class="samples" id="samples"></div>
    </section>
    <section class="results">
      <div class="summary">
        <label>Response Worker</label>
        <p class="answer empty" id="answer">Nhap cau hoi roi chay flow de xem supervisor, workers va trace.</p>
      </div>
      <div class="route" id="route">
        <span class="pill">Supervisor</span>
        <span class="pill">Policy Worker</span>
        <span class="pill">Data Worker</span>
        <span class="pill">Response Worker</span>
      </div>
      <div class="trace" id="trace"></div>
    </section>
  </main>
  <script>
    const question = document.querySelector("#question");
    const run = document.querySelector("#run");
    const answer = document.querySelector("#answer");
    const trace = document.querySelector("#trace");
    const route = document.querySelector("#route");
    const samples = document.querySelector("#samples");

    function renderRoute(payload) {
      const r = payload.route || {};
      route.innerHTML = "";
      [
        ["Supervisor", true],
        ["Policy Worker", r.needs_policy],
        ["Data Worker", r.needs_data],
        ["Response Worker", r.status !== "clarification_needed"],
      ].forEach(([name, active]) => {
        const item = document.createElement("span");
        item.className = "pill" + (active ? " on" : "");
        item.textContent = name;
        route.appendChild(item);
      });
      if (r.status === "clarification_needed") {
        const item = document.createElement("span");
        item.className = "pill warn";
        item.textContent = "Clarification";
        route.appendChild(item);
      }
    }

    function renderTrace(items) {
      trace.innerHTML = "";
      items.forEach((entry) => {
        const node = document.createElement("article");
        node.className = "node";
        const head = document.createElement("div");
        head.className = "node-head";
        head.innerHTML = `<span>${entry.node}</span><span>${entry.elapsed_s}s</span>`;
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(entry.output || entry, null, 2);
        node.append(head, pre);
        trace.appendChild(node);
      });
    }

    async function ask() {
      run.disabled = true;
      answer.className = "answer empty";
      answer.textContent = "Dang chay supervisor va workers...";
      try {
        const res = await fetch("/demo/ask", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({question: question.value})
        });
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.detail || "Request failed");
        answer.className = "answer";
        answer.textContent = payload.answer;
        renderRoute(payload);
        renderTrace(payload.trace || []);
      } catch (err) {
        answer.className = "answer error";
        answer.textContent = err.message;
      } finally {
        run.disabled = false;
      }
    }

    async function loadSamples() {
      const res = await fetch("/api/samples");
      const payload = await res.json();
      (payload.samples || []).forEach((text) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "sample";
        button.textContent = text;
        button.addEventListener("click", () => {
          question.value = text;
          ask();
        });
        samples.appendChild(button);
      });
    }

    run.addEventListener("click", ask);
    loadSamples();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    log_event("serve", host=settings.host, port=settings.port)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
