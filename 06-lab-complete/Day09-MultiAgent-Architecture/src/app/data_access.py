from __future__ import annotations

from pathlib import Path
from typing import Any


class ShoppingDataStore:
    """Student scaffold for mock-data lookup."""

    def __init__(self, json_path: Path) -> None:
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        self.metadata = data.get("metadata", {})
        self.customers = data.get("customers", [])
        self.orders = data.get("orders", [])
        self.vouchers = data.get("vouchers", [])
        
        # Build indices for O(1) lookups
        self._customer_by_id = {c["customer_id"]: c for c in self.customers}
        self._order_by_id = {o["order_id"]: o for o in self.orders}
        
        self._orders_by_customer_id = {}
        for o in self.orders:
            self._orders_by_customer_id.setdefault(o["customer_id"], []).append(o)
            
        self._vouchers_by_customer_id = {}
        for v in self.vouchers:
            self._vouchers_by_customer_id.setdefault(v["customer_id"], []).append(v)

    def get_customer_by_id(self, customer_id: str) -> dict[str, Any]:
        customer = self._customer_by_id.get(customer_id)
        if customer:
            return {"status": "ok", "customer": customer}
        return {"status": "not_found", "message": f"Customer {customer_id} not found."}

    def get_orders_by_customer_id(self, customer_id: str, limit: int = 10) -> dict[str, Any]:
        orders = self._orders_by_customer_id.get(customer_id, [])
        sorted_orders = sorted(orders, key=lambda x: x.get("created_at", ""), reverse=True)
        return {"status": "ok", "orders": sorted_orders[:limit]}

    def get_order_detail_by_order_id(self, order_id: str) -> dict[str, Any]:
        order = self._order_by_id.get(order_id)
        if order:
            return {"status": "ok", "order": order}
        return {"status": "not_found", "message": f"Order {order_id} not found."}

    def get_vouchers_by_customer_id(
        self,
        customer_id: str,
        only_active: bool = False,
    ) -> dict[str, Any]:
        vouchers = self._vouchers_by_customer_id.get(customer_id, [])
        if only_active:
            vouchers = [v for v in vouchers if v.get("status") == "active"]
        return {"status": "ok", "vouchers": vouchers}


def build_data_tools(store: ShoppingDataStore) -> list:
    from langchain_core.tools import tool

    @tool
    def get_customer_by_id(customer_id: str) -> dict[str, Any]:
        """Tra cứu thông tin khách hàng (tên, hạng, điểm, v.v.) bằng customer_id."""
        return store.get_customer_by_id(customer_id)

    @tool
    def get_orders_by_customer_id(customer_id: str, limit: int = 10) -> dict[str, Any]:
        """Tra cứu danh sách đơn hàng gần đây của một khách hàng bằng customer_id."""
        return store.get_orders_by_customer_id(customer_id, limit)

    @tool
    def get_order_detail_by_order_id(order_id: str) -> dict[str, Any]:
        """Tra cứu thông tin chi tiết của một đơn hàng cụ thể bằng order_id."""
        return store.get_order_detail_by_order_id(order_id)

    @tool
    def get_vouchers_by_customer_id(customer_id: str, only_active: bool = False) -> dict[str, Any]:
        """Tra cứu danh sách voucher của một khách hàng bằng customer_id. Đặt only_active=True để chỉ lấy voucher còn dùng được."""
        return store.get_vouchers_by_customer_id(customer_id, only_active)

    return [
        get_customer_by_id,
        get_orders_by_customer_id,
        get_order_detail_by_order_id,
        get_vouchers_by_customer_id
    ]
