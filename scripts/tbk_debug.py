import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from services.tbk_service import TBK_RECOMMEND_METHOD, TaobaoTbkService


async def main() -> int:
    settings = get_settings()
    print("TBK_DEBUG")
    print(f"app_key_set={bool(settings.tbk_app_key)}")
    print(f"app_secret_set={bool(settings.tbk_app_secret)}")
    print(f"adzone_id_set={bool(settings.tbk_effective_adzone_id)}")
    print(f"api_url={settings.tbk_api_url}")
    print(f"search_method={settings.tbk_search_method}")
    print(f"material_id={settings.tbk_material_id}")
    print(f"pid={settings.tbk_pid}")
    print(f"page_size={settings.tbk_page_size}")
    print(f"page_count={settings.tbk_page_count}")
    print(f"app_key_len={len(settings.tbk_app_key or '')}")
    print(f"secret_len={len(settings.tbk_app_secret or '')}")
    print(f"site_id={settings.tbk_effective_site_id}")
    print(f"adzone_id={settings.tbk_effective_adzone_id}")

    service = TaobaoTbkService(settings)
    if settings.tbk_search_method == TBK_RECOMMEND_METHOD:
        print("query_mode=local_title_relevance")
        print("query_note=recommend接口不支持q参数，系统会拉取官方物料后按商品标题本地匹配单品关键词")
        material_ids = service._material_ids()
        if not material_ids:
            print("TBK_RECOMMEND_ERROR")
            print("material_id=MISSING")
            print("msg=TBK_MATERIAL_ID 未配置")
            return 1

        has_success = False
        for material_id in material_ids:
            payload = await service._request_tbk_recommend(material_id)
            if "error_response" in payload:
                error = payload["error_response"]
                print("TBK_RECOMMEND_ERROR")
                print(f"material_id={material_id}")
                print(f"code={error.get('code')}")
                print(f"msg={error.get('msg')}")
                print(f"sub_code={error.get('sub_code')}")
                print(f"sub_msg={error.get('sub_msg')}")
                print(f"request_id={error.get('request_id')}")
                continue

            items = service._extract_map_data(payload)
            products = [product for product in (service._map_product(item) for item in items) if product]
            image_products = [product for product in products if product.image_url]
            print("TBK_RECOMMEND_OK")
            print(f"material_id={material_id}")
            print(f"raw_items={len(items)}")
            print(f"mapped_items={len(products)}")
            print(f"image_items={len(image_products)}")
            if products:
                first = products[0]
                print(f"first_title={first.title}")
                print(f"first_price={first.final_price}")
                print(f"first_image_set={bool(first.image_url)}")
                has_success = True
            if image_products:
                break
        return 0 if has_success else 1

    debug_keyword = "奶油风 沙发"
    debug_material_id = service._material_ids()[0] if service._material_ids() else None
    print(f"query_mode=remote_keyword")
    print(f"debug_keyword={debug_keyword}")
    print(f"debug_material_id={debug_material_id}")
    payload = await service._request_tbk(debug_keyword, "false", debug_material_id)
    if "error_response" in payload:
        error = payload["error_response"]
        print("TBK_ERROR")
        print(f"code={error.get('code')}")
        print(f"msg={error.get('msg')}")
        print(f"sub_code={error.get('sub_code')}")
        print(f"sub_msg={error.get('sub_msg')}")
        print(f"request_id={error.get('request_id')}")
        print("TBK_RECOMMEND_FALLBACK")
        fallback_material_ids = service._material_ids()
        if not fallback_material_ids:
            print("material_id=MISSING")
            return 1
        for material_id in fallback_material_ids:
            fallback = await service._request_tbk_recommend(material_id)
            if "error_response" in fallback:
                fallback_error = fallback["error_response"]
                print("TBK_RECOMMEND_FALLBACK_ERROR")
                print(f"material_id={material_id}")
                print(f"code={fallback_error.get('code')}")
                print(f"msg={fallback_error.get('msg')}")
                print(f"sub_code={fallback_error.get('sub_code')}")
                print(f"sub_msg={fallback_error.get('sub_msg')}")
                print(f"request_id={fallback_error.get('request_id')}")
                continue
            fallback_items = service._extract_map_data(fallback)
            products = [product for product in (service._map_product(item) for item in fallback_items) if product]
            image_products = [product for product in products if product.image_url]
            print("TBK_RECOMMEND_FALLBACK_OK")
            print(f"material_id={material_id}")
            print(f"raw_items={len(fallback_items)}")
            print(f"mapped_items={len(products)}")
            print(f"image_items={len(image_products)}")
            if products:
                first = products[0]
                print(f"first_title={first.title}")
                print(f"first_price={first.final_price}")
                print(f"first_image_set={bool(first.image_url)}")
                return 0
        return 1

    items = service._extract_map_data(payload)
    print("TBK_OK")
    print(f"raw_items={len(items)}")
    if items:
        products = [product for product in (service._map_product(item) for item in items) if product]
        image_products = [product for product in products if product.image_url]
        first = products[0] if products else None
        print(f"mapped_items={len(products)}")
        print(f"image_items={len(image_products)}")
        print(f"first_title={first.title if first else items[0].get('title')}")
        print(f"first_price={first.final_price if first else items[0].get('zk_final_price')}")
        print(f"first_image_set={bool(first and first.image_url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
