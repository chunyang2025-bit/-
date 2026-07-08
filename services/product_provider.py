from typing import List, Protocol

from app.config import Settings
from app.models import DesignItem, ProductMatch
from services.tbk_service import TaobaoTbkService


class ProductProvider(Protocol):
    name: str
    source_note: str
    last_errors: List[str]

    @property
    def is_configured(self) -> bool:
        ...

    async def search_matches(self, items: List[DesignItem], budget_max: int) -> List[ProductMatch]:
        ...


class TaobaoProductProvider:
    name = "tbk"
    source_note = "淘宝联盟 TBK 实时商品"

    def __init__(self, settings: Settings):
        self._service = TaobaoTbkService(settings)

    @property
    def is_configured(self) -> bool:
        return self._service.settings.has_tbk

    @property
    def last_errors(self) -> List[str]:
        return self._service.last_errors

    async def search_matches(self, items: List[DesignItem], budget_max: int) -> List[ProductMatch]:
        return await self._service.search_matches(items, budget_max)


class FallbackProductProvider:
    def __init__(self, name: str, fallback: ProductProvider):
        self.name = name
        self._fallback = fallback
        self.source_note = fallback.source_note
        self._initial_errors = [f"商品源 {name} 暂未接入，已回退 {fallback.name}"]

    @property
    def is_configured(self) -> bool:
        return self._fallback.is_configured

    @property
    def last_errors(self) -> List[str]:
        return self._initial_errors + self._fallback.last_errors

    async def search_matches(self, items: List[DesignItem], budget_max: int) -> List[ProductMatch]:
        return await self._fallback.search_matches(items, budget_max)


def build_product_provider(settings: Settings) -> ProductProvider:
    provider = (settings.product_provider or "tbk").lower()
    if provider in {"tbk", "taobao", "taobao_tbk"}:
        return TaobaoProductProvider(settings)
    return FallbackProductProvider(provider, TaobaoProductProvider(settings))
