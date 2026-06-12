from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any


DAY09_ROOT = Path(__file__).resolve().parents[1] / "Day09-MultiAgent-Architecture"
DATA_DIR = DAY09_ROOT / "data"
POLICY_PATH = DATA_DIR / "policy_mock_vi.md"
ORDERS_PATH = DATA_DIR / "order_customer_mock_data.json"


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return without_marks.replace("đ", "d")


def _parse_policy(markdown: str) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    current_h2 = ""
    current_h3 = ""
    current_content: list[str] = []

    def save_chunk() -> None:
        nonlocal current_content
        text = "\n".join(current_content).strip()
        if text and (current_h2 or current_h3):
            rendered = []
            if current_h2:
                rendered.append(f"## {current_h2}")
            if current_h3:
                rendered.append(f"### {current_h3}")
            rendered.append(text)
            chunks.append(
                {
                    "section_h2": current_h2,
                    "section_h3": current_h3,
                    "citation": current_h3 or current_h2,
                    "content": "\n\n".join(rendered),
                }
            )
        current_content = []

    for line in markdown.splitlines():
        if line.startswith("## "):
            save_chunk()
            current_h2 = line[3:].strip()
            current_h3 = ""
        elif line.startswith("### "):
            save_chunk()
            current_h3 = line[4:].strip()
        else:
            current_content.append(line)
    save_chunk()
    return chunks


class Day09DemoAgent:
    """Lightweight production demo for the Day09 multi-agent shopping flow.

    The full Day09 project can run LangGraph + real LLM providers. This class keeps
    the Railway demo responsive without secrets by using the same mock order data
    and policy document, then exposing the same supervisor/worker/response shape.
    """

    def __init__(self) -> None:
        raw_data = json.loads(ORDERS_PATH.read_text(encoding="utf-8"))
        self.metadata = raw_data.get("metadata", {})
        self.customers = raw_data.get("customers", [])
        self.orders = raw_data.get("orders", [])
        self.vouchers = raw_data.get("vouchers", [])
        self.policy_chunks = _parse_policy(POLICY_PATH.read_text(encoding="utf-8"))

        self.customer_by_id = {item["customer_id"].upper(): item for item in self.customers}
        self.order_by_id = {item["order_id"]: item for item in self.orders}
        self.orders_by_customer_id: dict[str, list[dict[str, Any]]] = {}
        self.vouchers_by_customer_id: dict[str, list[dict[str, Any]]] = {}

        for order in self.orders:
            self.orders_by_customer_id.setdefault(order["customer_id"].upper(), []).append(order)
        for voucher in self.vouchers:
            self.vouchers_by_customer_id.setdefault(voucher["customer_id"].upper(), []).append(voucher)

    def ask(self, question: str) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []

        t0 = time.time()
        route = self._supervise(question)
        trace.append(
            {
                "node": "supervisor",
                "elapsed_s": round(time.time() - t0, 3),
                "output": route,
            }
        )

        policy_result: dict[str, Any] | None = None
        data_result: dict[str, Any] | None = None

        if route["status"] == "clarification_needed":
            final_answer = route["clarification_question"]
        else:
            if route["needs_policy"]:
                t0 = time.time()
                policy_result = self._policy_worker(question)
                trace.append(
                    {
                        "node": "worker_1_policy",
                        "elapsed_s": round(time.time() - t0, 3),
                        "tool_calls": [
                            {
                                "tool": "search_policy",
                                "args": {"query": question},
                                "result_len": len(policy_result.get("facts", [])),
                            }
                        ],
                        "output": policy_result,
                    }
                )

            if route["needs_data"]:
                t0 = time.time()
                data_result = self._data_worker(question)
                trace.append(
                    {
                        "node": "worker_2_data",
                        "elapsed_s": round(time.time() - t0, 3),
                        "tool_calls": data_result.get("tool_calls", []),
                        "output": {k: v for k, v in data_result.items() if k != "tool_calls"},
                    }
                )

            t0 = time.time()
            final_answer = self._response_worker(question, route, policy_result, data_result)
            trace.append(
                {
                    "node": "worker_3_response",
                    "elapsed_s": round(time.time() - t0, 3),
                    "output": {"final_answer": final_answer},
                }
            )

        return {
            "route": route,
            "policy_result": policy_result,
            "data_result": data_result,
            "final_answer": final_answer,
            "trace": trace,
        }

    def samples(self) -> list[str]:
        return [
            "Don hang 1971 co duoc hoan tra khong?",
            "Don hang 2058 con trong thoi gian tra hang khong?",
            "Voucher cua khach hang C001 con ma nao dung duoc?",
            "Giao hang tieu chuan thuong mat bao lau?",
            "Voucher co duoc hoan lai khi huy don khong?",
        ]

    def _supervise(self, question: str) -> dict[str, Any]:
        text = _normalize(question)
        order_ids = re.findall(r"\b\d{4,}\b", question)
        customer_ids = re.findall(r"\bC\d{3,}\b", question.upper())
        mentions_my_data = any(token in text for token in ["cua toi", "don hang cua toi", "voucher cua toi"])

        data_intent = bool(order_ids or customer_ids) or any(
            token in text
            for token in [
                "don hang",
                "order",
                "khach hang",
                "customer",
                "trang thai",
                "ma nao",
                "quota",
                "hang gi",
            ]
        )
        policy_intent = any(
            token in text
            for token in [
                "chinh sach",
                "hoan tra",
                "tra hang",
                "doi tra",
                "giao hang",
                "giao nhanh",
                "tieu chuan",
                "voucher",
                "huy don",
                "kiem hang",
                "bao lau",
            ]
        )

        if mentions_my_data and not (order_ids or customer_ids):
            return {
                "status": "clarification_needed",
                "needs_policy": False,
                "needs_data": False,
                "clarification_question": "Ban vui long cung cap ma don hang hoac customer_id de minh tra cuu dung du lieu.",
            }

        return {
            "status": "ok",
            "needs_policy": policy_intent or not data_intent,
            "needs_data": data_intent,
            "clarification_question": None,
        }

    def _policy_worker(self, question: str) -> dict[str, Any]:
        stopwords = {
            "ban",
            "cho",
            "cua",
            "don",
            "duoc",
            "hang",
            "khach",
            "khong",
            "minh",
            "toi",
        }
        normalized_question = _normalize(question)
        query_terms = {
            term
            for term in re.findall(r"[a-z0-9]+", normalized_question)
            if len(term) > 2 and term not in stopwords
        }
        scored: list[tuple[int, dict[str, str]]] = []
        for chunk in self.policy_chunks:
            haystack = _normalize(chunk["content"])
            score = sum(1 for term in query_terms if term in haystack)
            if any(phrase in normalized_question for phrase in ["hoan tra", "tra hang", "doi tra"]):
                if "tra hang" in haystack or "hoan tien" in haystack:
                    score += 6
                if "15 ngay" in haystack or "chua the" in haystack:
                    score += 3
            if "voucher" in normalized_question and "voucher" in haystack:
                score += 5
            if "giao" in normalized_question and "giao hang" in haystack:
                score += 5
            if score:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        hits = [chunk for _, chunk in scored[:3]] or self.policy_chunks[:2]
        facts = [self._compact_fact(hit["content"]) for hit in hits]
        citations = [f"policy_mock_vi.md > {hit['citation']}" for hit in hits]
        return {
            "status": "ok" if facts else "not_found",
            "summary": "Tim thay cac doan policy lien quan trong knowledge base Day09.",
            "facts": facts,
            "citations": citations,
        }

    def _data_worker(self, question: str) -> dict[str, Any]:
        tool_calls: list[dict[str, Any]] = []
        facts: list[str] = []
        not_found: list[str] = []

        order_ids = re.findall(r"\b\d{4,}\b", question)
        customer_ids = re.findall(r"\bC\d{3,}\b", question.upper())
        text = _normalize(question)

        for order_id in order_ids:
            tool_calls.append({"tool": "get_order_detail_by_order_id", "args": {"order_id": order_id}})
            order = self.order_by_id.get(order_id)
            if not order:
                not_found.append(f"order:{order_id}")
                continue
            facts.extend(self._order_facts(order))
            customer_id = order.get("customer_id", "").upper()
            if customer_id and ("voucher" in text or "khach" in text):
                customer_ids.append(customer_id)

        for customer_id in dict.fromkeys(customer_ids):
            tool_calls.append({"tool": "get_customer_by_id", "args": {"customer_id": customer_id}})
            customer = self.customer_by_id.get(customer_id)
            if not customer:
                not_found.append(f"customer:{customer_id}")
                continue
            facts.append(
                f"Khach hang {customer_id} la {customer.get('customer_name')} hang {customer.get('tier')}; "
                f"quota voucher con lai thang nay: {customer.get('remaining_voucher_quota_this_month')}."
            )
            if "voucher" in text:
                only_active = any(token in text for token in ["con dung", "active", "dung duoc"])
                tool_calls.append(
                    {
                        "tool": "get_vouchers_by_customer_id",
                        "args": {"customer_id": customer_id, "only_active": only_active},
                    }
                )
                vouchers = self.vouchers_by_customer_id.get(customer_id, [])
                if only_active:
                    vouchers = [item for item in vouchers if item.get("status") == "active"]
                if vouchers:
                    codes = ", ".join(item["voucher_code"] for item in vouchers[:6])
                    facts.append(f"Voucher phu hop cua {customer_id}: {codes}.")
                else:
                    facts.append(f"Khong co voucher phu hop cho {customer_id}.")
            if "don" in text or "order" in text:
                tool_calls.append(
                    {"tool": "get_orders_by_customer_id", "args": {"customer_id": customer_id, "limit": 5}}
                )
                orders = sorted(
                    self.orders_by_customer_id.get(customer_id, []),
                    key=lambda item: item.get("created_at", ""),
                    reverse=True,
                )
                if orders:
                    facts.append(
                        "Don gan day: "
                        + ", ".join(f"{item['order_id']} ({item.get('order_status')})" for item in orders[:5])
                        + "."
                    )

        status = "not_found" if not facts and not_found else "ok"
        return {
            "status": status,
            "summary": "Da tra cuu mock order/customer/voucher data cua Day09." if facts else "Khong tim thay du lieu phu hop.",
            "facts": facts,
            "missing_fields": [],
            "not_found_entities": not_found,
            "tool_calls": tool_calls,
        }

    def _response_worker(
        self,
        question: str,
        route: dict[str, Any],
        policy_result: dict[str, Any] | None,
        data_result: dict[str, Any] | None,
    ) -> str:
        if data_result and data_result.get("status") == "not_found":
            missing = ", ".join(data_result.get("not_found_entities", []))
            return f"Minh chua tim thay du lieu cho {missing}. Vui long kiem tra lai ma don hang hoac customer_id."

        lines = ["Ket qua demo multi-agent Day09:"]
        if route.get("needs_data") and data_result:
            lines.append("Data Worker:")
            lines.extend(f"- {fact}" for fact in data_result.get("facts", [])[:5])
        if route.get("needs_policy") and policy_result:
            lines.append("Policy Worker:")
            lines.extend(f"- {fact}" for fact in policy_result.get("facts", [])[:3])
            citations = policy_result.get("citations", [])[:3]
            if citations:
                lines.append("Citation: " + " | ".join(citations))
        lines.append("Supervisor da route cau hoi theo nhu cau policy/data va Response Worker da tong hop cau tra loi.")
        return "\n".join(lines)

    def _order_facts(self, order: dict[str, Any]) -> list[str]:
        facts = [
            f"Don {order['order_id']} cua {order.get('customer_name')} dang o trang thai {order.get('order_status')}.",
            f"Ghi chu moi nhat: {order.get('latest_status_note')}",
            f"Van chuyen: {order.get('shipping_method')} qua {order.get('carrier')}, ETA {order.get('estimated_delivery')}.",
        ]
        if order.get("can_return_now"):
            facts.append(
                f"Don co the tao yeu cau tra hang hien tai; han ho tro den {order.get('eligible_for_return_until')}."
            )
        else:
            facts.append("Don chua the tao yeu cau tra hang ngay theo truong can_return_now=false.")
        return facts

    def _compact_fact(self, content: str) -> str:
        lines = [line.strip("- ").strip() for line in content.splitlines() if line.strip()]
        useful = [line for line in lines if not line.startswith("#")]
        return " ".join(useful[:3])[:360]
