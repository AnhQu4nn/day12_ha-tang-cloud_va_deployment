from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END

from app.config import Settings
from app.state import ShoppingState
from provider import get_chat_model
from app.data_access import ShoppingDataStore, build_data_tools
from rag.vector_store import ChromaPolicyStore
from rag.embeddings import SentenceTransformerEmbeddings
from app.prompts import (
    SUPERVISOR_PROMPT,
    POLICY_WORKER_PROMPT,
    DATA_WORKER_PROMPT,
    RESPONSE_WORKER_PROMPT,
    FORCE_JSON_EXTRACT,
)

# ---------------------------------------------------------
# Logger Setup
# ---------------------------------------------------------
logger = logging.getLogger("shopping_assistant")


def setup_logging(level: int = logging.INFO) -> None:
    """Configure rich console logging for the pipeline."""
    handler = logging.StreamHandler()
    handler.setLevel(level)
    fmt = logging.Formatter(
        "\033[90m%(asctime)s\033[0m "
        "\033[1m%(levelname)-8s\033[0m "
        "\033[36m%(name)s\033[0m │ %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(handler)


class ShoppingAssistant:
    """Multi-Agent LangGraph Shopping Assistant."""

    def __init__(self, settings: Settings | None = None) -> None:
        setup_logging()
        logger.info("═══════════════════════════════════════════════════")
        logger.info("  Initializing ShoppingAssistant pipeline …")
        logger.info("═══════════════════════════════════════════════════")
        t0 = time.time()

        self.settings = settings or Settings.load()
        logger.info("Provider: \033[33m%s\033[0m  Model: \033[33m%s\033[0m", self.settings.provider, self.settings.model)

        self.llm = get_chat_model(self.settings)
        logger.info("✅ Chat model loaded")

        self.data_store = ShoppingDataStore(self.settings.orders_path)
        self.data_tools = build_data_tools(self.data_store)
        logger.info("✅ Data store loaded — %d customers, %d orders, %d vouchers",
                     len(self.data_store.customers), len(self.data_store.orders), len(self.data_store.vouchers))

        self.embedding_model = SentenceTransformerEmbeddings(self.settings.embedding_model_name)
        self.policy_store = ChromaPolicyStore(
            persist_directory=self.settings.chroma_dir,
            embedding_model=self.embedding_model,
        )
        self.policy_store.ensure_index(self.settings.policy_path)
        logger.info("✅ Policy vector store ready — collection count: %d", self.policy_store.collection.count())

        @tool
        def search_policy(query: str) -> str:
            """Tìm kiếm thông tin chính sách, vận chuyển, hoàn trả, voucher."""
            hits = self.policy_store.search(query, top_k=self.settings.top_k)
            if not hits:
                return "Không tìm thấy thông tin chính sách phù hợp."
            return json.dumps(hits, ensure_ascii=False)

        self.policy_tools = [search_policy]
        self.graph = build_graph(self.llm, self.policy_tools, self.data_tools)

        elapsed = time.time() - t0
        logger.info("✅ Graph compiled — init took \033[32m%.2fs\033[0m", elapsed)
        logger.info("═══════════════════════════════════════════════════\n")

    def ask(
        self,
        question: str,
        trace_file: Path | None = None,
        rebuild_index: bool = False,
    ) -> dict[str, Any]:
        logger.info("───────────────────────────────────────────────────")
        logger.info("📩 NEW QUESTION: %s", question)
        logger.info("───────────────────────────────────────────────────")
        t0 = time.time()

        if rebuild_index:
            logger.info("🔄 Rebuilding Chroma index …")
            self.policy_store.rebuild(self.settings.policy_path)

        initial_state = {"question": question, "trace": []}
        result = self.graph.invoke(initial_state)
        elapsed = time.time() - t0

        if trace_file:
            trace_file.parent.mkdir(parents=True, exist_ok=True)
            with open(trace_file, "w", encoding="utf-8") as f:
                json.dump(result.get("trace", []), f, ensure_ascii=False, indent=2)
            logger.info("💾 Trace saved → %s", trace_file)

        logger.info("⏱️  Total pipeline time: \033[32m%.2fs\033[0m", elapsed)
        logger.info("───────────────────────────────────────────────────\n")

        return {
            "route": result.get("route"),
            "policy_result": result.get("policy_result"),
            "data_result": result.get("data_result"),
            "final_answer": result.get("final_answer"),
            "trace": result.get("trace", []),
        }

    def run_batch(
        self,
        test_file: Path,
        output_dir: Path,
        rebuild_index: bool = False,
    ) -> dict[str, Any]:
        logger.info("🗂️  Batch mode — reading %s", test_file)
        if rebuild_index:
            self.policy_store.rebuild(self.settings.policy_path)

        with open(test_file, "r", encoding="utf-8") as f:
            test_data = json.load(f)

        output_dir.mkdir(parents=True, exist_ok=True)
        summary = []

        for i, case in enumerate(test_data):
            q = case.get("question", "")
            logger.info("🗂️  [%d/%d] %s", i + 1, len(test_data), q)
            trace_path = output_dir / f"trace_{i}.json"
            res = self.ask(q, trace_file=trace_path)
            summary.append({
                "question": q,
                "final_answer": res["final_answer"],
                "trace_file": str(trace_path),
            })

        with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info("✅ Batch done — %d cases processed", len(test_data))
        return {"status": "ok", "processed": len(test_data)}


# ---------------------------------------------------------
# Pydantic Schemas (kept for reference / future use)
# ---------------------------------------------------------

class RouteSchema(BaseModel):
    status: Literal["ok", "clarification_needed"] = Field(...)
    needs_policy: bool = Field(...)
    needs_data: bool = Field(...)
    clarification_question: str | None = Field(default=None)

class PolicyResultSchema(BaseModel):
    status: Literal["ok", "not_found"] = Field(...)
    summary: str = Field(...)
    facts: list[str] = Field(...)
    citations: list[str] = Field(...)

class DataResultSchema(BaseModel):
    status: Literal["ok", "clarification_needed", "not_found"] = Field(...)
    summary: str = Field(...)
    facts: list[str] = Field(...)
    missing_fields: list[str] = Field(default_factory=list)
    not_found_entities: list[str] = Field(default_factory=list)


# ---------------------------------------------------------
# Graph Definition
# ---------------------------------------------------------

def build_graph(llm: Any, policy_tools: list, data_tools: list) -> Any:

    def extract_json(content: str) -> dict:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            return {}

    # ─── Supervisor ──────────────────────────────────────
    def supervisor_node(state: ShoppingState) -> dict:
        logger.info("🧠 \033[1m[SUPERVISOR]\033[0m Routing question …")
        t0 = time.time()

        res = llm.invoke([
            SystemMessage(content=SUPERVISOR_PROMPT),
            HumanMessage(content=state.get("question", "")),
        ])
        raw = res.content
        logger.debug("   LLM raw ▸ %s", raw[:300])

        route = extract_json(raw)
        if not route:
            route = {"status": "ok", "needs_policy": True, "needs_data": True, "clarification_question": None}
            logger.warning("   ⚠️  JSON parse failed — defaulting to both workers")

        elapsed = time.time() - t0
        logger.info("   Route → status=\033[33m%s\033[0m  policy=\033[33m%s\033[0m  data=\033[33m%s\033[0m  (%.2fs)",
                     route.get("status"), route.get("needs_policy"), route.get("needs_data"), elapsed)
        if route.get("clarification_question"):
            logger.info("   ❓ Clarification: %s", route["clarification_question"])

        trace_entry = {
            "node": "supervisor",
            "elapsed_s": round(elapsed, 3),
            "llm_raw": raw,
            "output": route,
        }
        return {"route": route, "trace": [trace_entry]}

    # ─── Policy Worker ───────────────────────────────────
    def worker_1_policy_node(state: ShoppingState) -> dict:
        logger.info("📜 \033[1m[POLICY WORKER]\033[0m Starting RAG retrieval …")
        t0 = time.time()
        tool_trace = []

        llm_with_tools = llm.bind_tools(policy_tools)
        messages = [
            SystemMessage(content=POLICY_WORKER_PROMPT),
            HumanMessage(content=state.get("question", "")),
        ]

        final_content = ""
        for step in range(3):
            response = llm_with_tools.invoke(messages)
            if not getattr(response, "tool_calls", []):
                logger.info("   Step %d — no tool calls, finishing loop", step + 1)
                final_content = response.content
                break

            messages.append(response)
            for tc in response.tool_calls:
                logger.info("   🔧 Tool call: \033[35m%s\033[0m(%s)", tc["name"], json.dumps(tc["args"], ensure_ascii=False)[:120])
                tool_func = next(t for t in policy_tools if t.name == tc["name"])
                try:
                    tool_res = tool_func.invoke(tc["args"])
                except Exception as e:
                    tool_res = str(e)
                    logger.error("   ❌ Tool error: %s", e)
                tool_trace.append({"tool": tc["name"], "args": tc["args"], "result_len": len(str(tool_res))})
                messages.append(ToolMessage(content=str(tool_res), tool_call_id=tc["id"]))

        if not final_content:
            # Force final JSON synthesis — no tools allowed in this call
            messages.append(HumanMessage(
                content=FORCE_JSON_EXTRACT + """
Return ONLY valid JSON matching:
{"status": "ok"|"not_found", "summary": "...", "facts": [...], "citations": [...]}"""
            ))
            forced = llm.invoke(messages)
            final_content = forced.content
            logger.debug("   Forced JSON response: %s", final_content[:300])

        try:
            res_dict = extract_json(final_content)
            if not res_dict:
                logger.error("Failed to parse: %s", final_content)
                raise ValueError("Could not parse JSON output")
            logger.info("   ✅ Policy result parsed — status=\033[33m%s\033[0m, %d facts, %d citations",
                         res_dict.get("status"), len(res_dict.get("facts", [])), len(res_dict.get("citations", [])))
        except Exception as e:
            logger.error("   ❌ Policy extraction error: %s", e)
            res_dict = {"status": "not_found", "summary": f"Error: {e}", "facts": [], "citations": []}

        elapsed = time.time() - t0
        logger.info("   ⏱️  Policy worker took \033[32m%.2fs\033[0m", elapsed)

        trace_entry = {
            "node": "worker_1_policy",
            "elapsed_s": round(elapsed, 3),
            "tool_calls": tool_trace,
            "output": res_dict,
        }
        return {"policy_result": res_dict, "trace": [trace_entry]}

    # ─── Data Worker ─────────────────────────────────────
    def worker_2_data_node(state: ShoppingState) -> dict:
        logger.info("🗄️  \033[1m[DATA WORKER]\033[0m Looking up order/customer data …")
        t0 = time.time()
        tool_trace = []

        llm_with_tools = llm.bind_tools(data_tools)
        messages = [
            SystemMessage(content=DATA_WORKER_PROMPT),
            HumanMessage(content=state.get("question", "")),
        ]

        final_content = ""
        for step in range(5):
            response = llm_with_tools.invoke(messages)
            if not getattr(response, "tool_calls", []):
                logger.info("   Step %d — no tool calls, finishing loop", step + 1)
                final_content = response.content
                break

            messages.append(response)
            for tc in response.tool_calls:
                logger.info("   🔧 Tool call: \033[35m%s\033[0m(%s)", tc["name"], json.dumps(tc["args"], ensure_ascii=False)[:120])
                tool_func = next(t for t in data_tools if t.name == tc["name"])
                try:
                    tool_res = tool_func.invoke(tc["args"])
                except Exception as e:
                    tool_res = str(e)
                    logger.error("   ❌ Tool error: %s", e)
                tool_trace.append({"tool": tc["name"], "args": tc["args"], "result_preview": str(tool_res)[:200]})
                messages.append(ToolMessage(content=str(tool_res), tool_call_id=tc["id"]))

        if not final_content:
            # Force final JSON synthesis — no tools allowed in this call
            messages.append(HumanMessage(
                content=FORCE_JSON_EXTRACT + """
Return ONLY valid JSON matching:
{"status": "ok"|"clarification_needed"|"not_found", "summary": "...", "facts": [...], "missing_fields": [...], "not_found_entities": [...]}"""
            ))
            forced = llm.invoke(messages)
            final_content = forced.content
            logger.debug("   Forced JSON response: %s", final_content[:300])

        try:
            res_dict = extract_json(final_content)
            if not res_dict:
                logger.error("Failed to parse: %s", final_content)
                raise ValueError("Could not parse JSON output")
            logger.info("   ✅ Data result parsed — status=\033[33m%s\033[0m, %d facts",
                         res_dict.get("status"), len(res_dict.get("facts", [])))
        except Exception as e:
            logger.error("   ❌ Data extraction error: %s", e)
            res_dict = {"status": "not_found", "summary": f"Error: {e}", "facts": [], "missing_fields": [], "not_found_entities": []}

        elapsed = time.time() - t0
        logger.info("   ⏱️  Data worker took \033[32m%.2fs\033[0m", elapsed)

        trace_entry = {
            "node": "worker_2_data",
            "elapsed_s": round(elapsed, 3),
            "tool_calls": tool_trace,
            "output": res_dict,
        }
        return {"data_result": res_dict, "trace": [trace_entry]}

    # ─── Response Worker ─────────────────────────────────
    def worker_3_response_node(state: ShoppingState) -> dict:
        logger.info("💬 \033[1m[RESPONSE WORKER]\033[0m Synthesizing final answer …")
        t0 = time.time()

        ctx = f"Supervisor Route: {json.dumps(state.get('route', {}), ensure_ascii=False)}\n"
        if "policy_result" in state:
            ctx += f"Policy Result: {json.dumps(state.get('policy_result', {}), ensure_ascii=False)}\n"
        if "data_result" in state:
            ctx += f"Data Result: {json.dumps(state.get('data_result', {}), ensure_ascii=False)}\n"

        res = llm.invoke([
            SystemMessage(content=RESPONSE_WORKER_PROMPT),
            HumanMessage(content=f"User Question: {state.get('question', '')}\n\nContext:\n{ctx}"),
        ])
        ans = res.content

        elapsed = time.time() - t0
        logger.info("   ✅ Final answer generated (\033[32m%.2fs\033[0m, %d chars)", elapsed, len(ans))

        trace_entry = {
            "node": "worker_3_response",
            "elapsed_s": round(elapsed, 3),
            "output": {"final_answer": ans},
        }
        return {"final_answer": ans, "trace": [trace_entry]}

    # ─── Routing Logic ───────────────────────────────────
    def route_after_supervisor(state: ShoppingState):
        route = state.get("route", {})
        if route.get("status") == "clarification_needed":
            logger.info("🔀 Routing → \033[33mresponse\033[0m (clarification needed)")
            return ["response"]

        next_nodes = []
        if route.get("needs_policy"):
            next_nodes.append("policy")
        if route.get("needs_data"):
            next_nodes.append("data")

        if not next_nodes:
            next_nodes = ["response"]

        logger.info("🔀 Routing → \033[33m%s\033[0m", ", ".join(next_nodes))
        return next_nodes

    # ─── Compile Graph ───────────────────────────────────
    workflow = StateGraph(ShoppingState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("policy", worker_1_policy_node)
    workflow.add_node("data", worker_2_data_node)
    workflow.add_node("response", worker_3_response_node)

    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges("supervisor", route_after_supervisor, ["policy", "data", "response"])
    workflow.add_edge("policy", "response")
    workflow.add_edge("data", "response")
    workflow.add_edge("response", END)

    return workflow.compile()
