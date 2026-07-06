import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from services.tbk_service import TaobaoTbkService


async def main() -> int:
    settings = get_settings()
    print("TBK_DEBUG")
    print(f"app_key_set={bool(settings.tbk_app_key)}")
    print(f"app_secret_set={bool(settings.tbk_app_secret)}")
    print(f"adzone_id_set={bool(settings.tbk_adzone_id)}")
    print(f"api_url={settings.tbk_api_url}")
    print(f"search_method={settings.tbk_search_method}")
    print(f"app_key_len={len(settings.tbk_app_key or '')}")
    print(f"secret_len={len(settings.tbk_app_secret or '')}")
    print(f"adzone_id={settings.tbk_adzone_id}")

    service = TaobaoTbkService(settings)
    payload = await service._request_tbk("奶油风 沙发", "false")
    if "error_response" in payload:
        error = payload["error_response"]
        print("TBK_ERROR")
        print(f"code={error.get('code')}")
        print(f"msg={error.get('msg')}")
        print(f"sub_code={error.get('sub_code')}")
        print(f"sub_msg={error.get('sub_msg')}")
        print(f"request_id={error.get('request_id')}")
        fallback = await service._request_tbk_item_get("奶油风 沙发")
        if "error_response" in fallback:
            fallback_error = fallback["error_response"]
            print("TBK_FALLBACK_ERROR")
            print(f"code={fallback_error.get('code')}")
            print(f"msg={fallback_error.get('msg')}")
            print(f"sub_code={fallback_error.get('sub_code')}")
            print(f"sub_msg={fallback_error.get('sub_msg')}")
            print(f"request_id={fallback_error.get('request_id')}")
            return 1
        fallback_items = (
            fallback.get("tbk_item_get_response", {})
            .get("results", {})
            .get("n_tbk_item", [])
        )
        print("TBK_FALLBACK_OK")
        print(f"raw_items={len(fallback_items)}")
        if fallback_items:
            first = fallback_items[0]
            print(f"first_title={first.get('title')}")
            print(f"first_price={first.get('zk_final_price')}")
            print(f"first_image_set={bool(first.get('pict_url'))}")
        return 0

    items = (
        payload.get("tbk_dg_material_optional_response", {})
        .get("result_list", {})
        .get("map_data", [])
    )
    print("TBK_OK")
    print(f"raw_items={len(items)}")
    if items:
        first = items[0]
        print(f"first_title={first.get('title')}")
        print(f"first_price={first.get('zk_final_price')}")
        print(f"first_image_set={bool(first.get('pict_url'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
