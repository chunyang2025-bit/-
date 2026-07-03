import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from app.main import app


def main() -> int:
    client = TestClient(app)
    health = client.get("/api/health")
    health.raise_for_status()

    payload = {
        "space_type": "客厅",
        "house_property": "租房",
        "decor_style": "奶油风",
        "area_sqm": 38,
        "budget_min": 3000,
        "budget_max": 9000,
        "video_focus": "平价软装",
    }
    response = client.post("/api/run_full_pipeline", json=payload)
    response.raise_for_status()
    data = response.json()

    video_path = Path(data["video"]["video_path"])
    excel_path = Path(data["excel"]["excel_path"])
    assert video_path.exists() and video_path.stat().st_size > 0, video_path
    assert excel_path.exists() and excel_path.stat().st_size > 0, excel_path
    assert data["design_plan"]["items"], "missing design items"
    assert data["products"]["matches"], "missing product matches"
    products = [product for match in data["products"]["matches"] for product in match["products"]]
    realtime_count = sum(1 for product in products if product["is_realtime"])
    image_count = sum(1 for product in products if product.get("image_url"))

    print("SMOKE_OK")
    print(f"video={video_path}")
    print(f"excel={excel_path}")
    print(f"products={len(products)}")
    print(f"realtime_products={realtime_count}")
    print(f"product_images={image_count}")
    if data.get("warnings"):
        print("warnings=" + " | ".join(data["warnings"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
