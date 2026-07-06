import hashlib
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

from app.config import Settings
from app.models import DesignItem, Product, ProductMatch


TBK_RECOMMEND_METHOD = "taobao.tbk.dg.material.recommend"
TBK_OPTIONAL_METHODS = {
    "taobao.tbk.dg.material.optional",
    "taobao.tbk.dg.material.temporary.optional",
}


class TaobaoTbkService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_errors: List[str] = []

    async def search_matches(self, items: List[DesignItem], budget_max: int) -> List[ProductMatch]:
        self.last_errors = []
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
                self.last_errors.append(f"{item.name}: TBK 返回商品为空或被筛选条件过滤")
            except Exception:
                self.last_errors.append(f"{item.name}: TBK 查询失败")
        return self._demo_products(item, budget_max)

    async def _search_tbk(self, item: DesignItem, budget_max: int) -> List[Product]:
        raw_items: List[Dict[str, Any]] = []
        if self.settings.tbk_search_method == TBK_RECOMMEND_METHOD:
            return await self._search_recommend_products(item, budget_max)
        else:
            optional_request_failed = False
            material_ids: List[Optional[str]] = self._material_ids() or [None]
            for material_id in material_ids:
                for has_coupon in ["true", "false"]:
                    payload = await self._request_tbk(item.taobao_keyword, has_coupon, material_id)
                    error = payload.get("error_response")
                    if error:
                        optional_request_failed = True
                        suffix = f" material_id={material_id}" if material_id else ""
                        self.last_errors.append(
                            f"{item.name}: TBK optional 错误{suffix} "
                            f"{error.get('sub_msg') or error.get('msg') or error.get('code')}"
                        )
                        continue
                    raw_items = self._extract_map_data(payload)
                    if raw_items:
                        suffix = f" material_id={material_id}" if material_id else ""
                        self.last_errors.append(
                            f"{item.name}: 使用 {self.settings.tbk_search_method} 关键词搜索{suffix}"
                        )
                        break
                if raw_items:
                    break
            if not raw_items and optional_request_failed:
                self.last_errors.append(f"{item.name}: optional 接口暂不可用，自动回退 taobao.tbk.dg.material.recommend")
                return await self._search_recommend_products(item, budget_max)

        if not raw_items and self.settings.tbk_search_method not in {
            TBK_RECOMMEND_METHOD,
            *TBK_OPTIONAL_METHODS,
        }:
            fallback_payload = await self._request_tbk_item_get(item.taobao_keyword)
            error = fallback_payload.get("error_response")
            if error:
                self.last_errors.append(f"{item.name}: TBK 备用查询错误 {error.get('sub_msg') or error.get('msg') or error.get('code')}")
            raw_items = (
                fallback_payload.get("tbk_item_get_response", {})
                .get("results", {})
                .get("n_tbk_item", [])
            )
            if raw_items:
                self.last_errors.append(f"{item.name}: 使用 taobao.tbk.item.get 备用真实商品查询")

        products = [p for p in (self._map_product(raw) for raw in raw_items) if p]
        return self._filter_products(products, item, budget_max)

    async def _search_recommend_products(self, item: DesignItem, budget_max: int) -> List[Product]:
        material_ids = self._material_ids()
        if not material_ids:
            self.last_errors.append(f"{item.name}: TBK_MATERIAL_ID 未配置")
        for material_id in material_ids:
            payload = await self._request_tbk_recommend(material_id)
            error = payload.get("error_response")
            if error:
                self.last_errors.append(
                    f"{item.name}: TBK 物料精选错误 material_id={material_id} "
                    f"{error.get('sub_msg') or error.get('msg') or error.get('code')}"
                )
                continue
            raw_items = self._extract_map_data(payload)
            products = [p for p in (self._map_product(raw) for raw in raw_items) if p]
            relevant_products = self._relevant_products(products, item)
            if not relevant_products and products:
                self.last_errors.append(f"{item.name}: material_id={material_id} 有返回但未命中单品关键词，已跳过")
                continue
            filtered = self._filter_products(relevant_products, item, budget_max)
            if filtered:
                self.last_errors.append(
                    f"{item.name}: 使用 taobao.tbk.dg.material.recommend 官方物料 material_id={material_id}"
                )
                return filtered
            if raw_items:
                self.last_errors.append(f"{item.name}: material_id={material_id} 有返回但未匹配预算/图片/关键词")
        return []

    async def _request_tbk(
        self,
        keyword: str,
        has_coupon: str,
        material_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "method": self.settings.tbk_search_method,
            "app_key": self.settings.tbk_app_key,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "adzone_id": self.settings.tbk_adzone_id,
            "q": keyword,
            "page_size": "20",
            "sort": "total_sales_des",
            "platform": "2",
            "has_coupon": has_coupon,
        }
        if self.settings.tbk_site_id:
            params["site_id"] = self.settings.tbk_site_id
        if material_id and self.settings.tbk_search_method in TBK_OPTIONAL_METHODS:
            params["material_id"] = material_id
        params["sign"] = self._sign(params)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.settings.tbk_api_url, params=params)
            response.raise_for_status()
            return response.json()

    async def _request_tbk_recommend(self, material_id: Optional[str] = None) -> Dict[str, Any]:
        selected_material_id = material_id or (self._material_ids()[0] if self._material_ids() else None)
        if not selected_material_id:
            return {
                "error_response": {
                    "code": "LOCAL_MISSING_MATERIAL_ID",
                    "msg": "TBK_MATERIAL_ID 未配置",
                }
            }
        params = {
            "method": TBK_RECOMMEND_METHOD,
            "app_key": self.settings.tbk_app_key,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "adzone_id": self.settings.tbk_adzone_id,
            "material_id": selected_material_id,
            "page_no": "1",
            "page_size": "100",
        }
        params["sign"] = self._sign(params)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.settings.tbk_api_url, params=params)
            response.raise_for_status()
            return response.json()

    async def _request_tbk_item_get(self, keyword: str) -> Dict[str, Any]:
        params = {
            "method": "taobao.tbk.item.get",
            "app_key": self.settings.tbk_app_key,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "fields": "num_iid,title,pict_url,small_images,reserve_price,zk_final_price,user_type,provcity,item_url,nick,volume",
            "q": keyword,
            "page_no": "1",
            "page_size": "20",
            "sort": "total_sales_des",
            "platform": "2",
        }
        params["sign"] = self._sign(params)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.settings.tbk_api_url, params=params)
            response.raise_for_status()
            return response.json()

    def _sign(self, params: Dict[str, Any]) -> str:
        assert self.settings.tbk_app_secret
        ordered = "".join(f"{key}{params[key]}" for key in sorted(params) if params[key] is not None and key != "sign")
        raw = f"{self.settings.tbk_app_secret}{ordered}{self.settings.tbk_app_secret}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    def _material_ids(self) -> List[str]:
        raw = self.settings.tbk_material_id or ""
        return [part.strip() for part in re.split(r"[,，\s]+", raw) if part.strip()]

    @staticmethod
    def _extract_map_data(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        response_keys = [
            "tbk_dg_material_optional_response",
            "tbk_dg_material_temporary_optional_response",
            "tbk_dg_material_recommend_response",
        ]
        for key in response_keys:
            items = (
                payload.get(key, {})
                .get("result_list", {})
                .get("map_data", [])
            )
            if items:
                return items
        for value in payload.values():
            if not isinstance(value, dict):
                continue
            items = value.get("result_list", {}).get("map_data", [])
            if items:
                return items
        return []

    def _relevant_products(self, products: List[Product], item: DesignItem) -> List[Product]:
        tokens = self._relevance_tokens(item)
        if not tokens:
            return products
        return [
            product
            for product in products
            if any(token in f"{product.title} {product.shop_name}" for token in tokens)
        ]

    @staticmethod
    def _relevance_tokens(item: DesignItem) -> List[str]:
        text = f"{item.name} {item.material} {item.scene} {item.taobao_keyword}"
        seeds = [
            "沙发",
            "茶几",
            "桌",
            "柜",
            "灯",
            "窗帘",
            "地毯",
            "床",
            "椅",
            "置物",
            "收纳",
            "挂画",
            "抱枕",
            "床品",
            "镜",
            "餐具",
        ]
        return [token for token in seeds if token in text]

    def _map_product(self, raw: Dict[str, Any]) -> Optional[Product]:
        try:
            basic = raw.get("item_basic_info") if isinstance(raw.get("item_basic_info"), dict) else raw
            price_info = raw.get("price_promotion_info") if isinstance(raw.get("price_promotion_info"), dict) else raw
            publish_info = raw.get("publish_info") if isinstance(raw.get("publish_info"), dict) else raw
            income_info = publish_info.get("income_info") if isinstance(publish_info.get("income_info"), dict) else publish_info
            price = float(price_info.get("zk_final_price") or price_info.get("reserve_price") or basic.get("zk_final_price") or basic.get("reserve_price") or 0)
            final_price = float(price_info.get("final_promotion_price") or price)
            coupon_amount = max(price - final_price, 0)
            coupon_price = final_price if final_price else max(price - coupon_amount, 0)
            image_url = basic.get("pict_url") or basic.get("white_image") or self._first_small_image(basic)
            item_url = (
                publish_info.get("coupon_share_url")
                or publish_info.get("click_url")
                or raw.get("coupon_share_url")
                or raw.get("url")
                or raw.get("item_url")
            )
            commission_rate = (
                income_info.get("commission_rate")
                or publish_info.get("income_rate")
                or raw.get("commission_rate")
                or 0
            )
            return Product(
                item_id=str(raw.get("num_iid") or raw.get("item_id") or basic.get("item_id")),
                title=basic.get("title") or raw.get("title") or "淘宝在售商品",
                price=price,
                original_price=float(price_info.get("reserve_price") or basic.get("reserve_price") or price),
                coupon_price=coupon_price,
                image_url=self._normalize_image(image_url),
                item_url=self._normalize_url(item_url),
                shop_name=basic.get("shop_title") or raw.get("shop_title") or raw.get("nick") or "淘宝店铺",
                commission_rate=float(commission_rate) / 100,
                sales=int(basic.get("volume") or raw.get("volume") or 0),
                source="淘宝联盟 TBK",
                is_realtime=True,
            )
        except (TypeError, ValueError):
            return None

    def _filter_products(self, products: List[Product], item: DesignItem, budget_max: int) -> List[Product]:
        max_item_price = min(item.suggested_price_max * 1.35, budget_max)
        with_images = [product for product in products if product.item_url and product.image_url and product.final_price <= max_item_price]
        strict = [
            product
            for product in with_images
            if product.commission_rate >= self.settings.tbk_min_commission_rate / 100
            and product.sales >= self.settings.tbk_min_sales
        ]
        if strict:
            return sorted(strict, key=lambda product: (-product.sales, product.final_price))
        if with_images and not self.settings.tbk_strict_filters:
            self.last_errors.append(f"{item.name}: 使用真实带图商品备选，未完全满足佣金/销量严格筛选")
            return sorted(with_images, key=lambda product: (-product.sales, product.final_price))
        return []

    @staticmethod
    def _first_small_image(raw: Dict[str, Any]) -> Optional[str]:
        small_images = raw.get("small_images") or {}
        values = small_images.get("string") or []
        if isinstance(values, list) and values:
            return values[0]
        return None

    @staticmethod
    def _normalize_image(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        if url.startswith("//"):
            return f"https:{url}"
        return url

    @staticmethod
    def _normalize_url(url: Optional[str]) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"https://{url.lstrip('/')}"

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
                    item_url=f"https://s.taobao.com/search?q={quote_plus(item.taobao_keyword)}",
                    shop_name="演示淘宝店铺",
                    commission_rate=12 + index,
                    sales=300 + index * 120,
                    source="虚拟商品演示，非淘宝真实商品",
                    is_realtime=False,
                )
            )
        return products
