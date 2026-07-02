import hashlib
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings
from app.models import DesignItem, Product, ProductMatch


class TaobaoTbkService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def search_matches(self, items: List[DesignItem], budget_max: int) -> List[ProductMatch]:
        matches = []
        for item in items:
            products = await self.search_item(item, budget_max)
            matches.append(ProductMatch(design_item=item, products=products[:3]))
        return matches

    async def search_item(self, item: DesignItem, budget_max: int) -> List[Product]:
        if self.settings.has_tbk:
            try:
                products = await self._search_tbk(item, budget_max)
                if products:
                    return products[:3]
            except Exception:
                pass
        return self._demo_products(item, budget_max)

    async def _search_tbk(self, item: DesignItem, budget_max: int) -> List[Product]:
        params = {
            "method": "taobao.tbk.dg.material.optional",
            "app_key": self.settings.tbk_app_key,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "adzone_id": self.settings.tbk_adzone_id,
            "q": item.taobao_keyword,
            "page_size": "20",
            "sort": "total_sales_des",
            "platform": "2",
            "has_coupon": "true",
        }
        if self.settings.tbk_site_id:
            params["site_id"] = self.settings.tbk_site_id
        params["sign"] = self._sign(params)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.settings.tbk_api_url, params=params)
            response.raise_for_status()
            payload = response.json()
        raw_items = (
            payload.get("tbk_dg_material_optional_response", {})
            .get("result_list", {})
            .get("map_data", [])
        )
        products = [p for p in (self._map_product(raw) for raw in raw_items) if p]
        return self._filter_products(products, item, budget_max)

    def _sign(self, params: Dict[str, Any]) -> str:
        assert self.settings.tbk_app_secret
        ordered = "".join(f"{key}{params[key]}" for key in sorted(params) if params[key] is not None and key != "sign")
        raw = f"{self.settings.tbk_app_secret}{ordered}{self.settings.tbk_app_secret}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    def _map_product(self, raw: Dict[str, Any]) -> Optional[Product]:
        try:
            price = float(raw.get("zk_final_price") or raw.get("reserve_price") or 0)
            coupon_amount = float(raw.get("coupon_amount") or 0)
            coupon_price = max(price - coupon_amount, 0) if coupon_amount else price
            return Product(
                item_id=str(raw.get("num_iid") or raw.get("item_id")),
                title=raw.get("title") or "淘宝在售商品",
                price=price,
                original_price=float(raw.get("reserve_price") or price),
                coupon_price=coupon_price,
                image_url=self._normalize_image(raw.get("pict_url")),
                item_url=raw.get("coupon_share_url") or raw.get("url") or raw.get("item_url") or "",
                shop_name=raw.get("shop_title") or "淘宝店铺",
                commission_rate=float(raw.get("commission_rate") or 0) / 100,
                sales=int(raw.get("volume") or 0),
                source="淘宝联盟 TBK",
                is_realtime=True,
            )
        except (TypeError, ValueError):
            return None

    def _filter_products(self, products: List[Product], item: DesignItem, budget_max: int) -> List[Product]:
        max_item_price = min(item.suggested_price_max * 1.35, budget_max)
        filtered = [
            product
            for product in products
            if product.final_price <= max_item_price
            and product.commission_rate >= self.settings.tbk_min_commission_rate / 100
            and product.sales >= self.settings.tbk_min_sales
            and product.item_url
        ]
        return sorted(filtered, key=lambda product: (-product.sales, product.final_price))

    @staticmethod
    def _normalize_image(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        if url.startswith("//"):
            return f"https:{url}"
        return url

    def _demo_products(self, item: DesignItem, budget_max: int) -> List[Product]:
        base = max(item.suggested_price_min, 1)
        upper = min(max(item.suggested_price_max, base), max(budget_max, base))
        points = [base, int((base + upper) / 2), upper]
        products = []
        for index, price in enumerate(points, start=1):
            products.append(
                Product(
                    item_id=f"DEMO-{hash(item.taobao_keyword) % 100000}-{index}",
                    title=f"{item.taobao_keyword} 演示商品 {index}",
                    price=float(round(price * 1.12, 2)),
                    original_price=float(round(price * 1.2, 2)),
                    coupon_price=float(price),
                    image_url=None,
                    item_url=f"https://s.taobao.com/search?q={item.taobao_keyword}",
                    shop_name="演示淘宝店铺",
                    commission_rate=12 + index,
                    sales=300 + index * 120,
                    source="演示数据，接入 TBK 后替换为淘宝联盟实时商品",
                    is_realtime=False,
                )
            )
        return products
