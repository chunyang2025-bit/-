import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


def main() -> int:
    settings = get_settings()
    render_files = sorted(settings.renders_dir.glob("*.jpg"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not render_files:
        print("PUBLIC_ASSET_CHECK=false")
        print("reason=no_render_files")
        print("hint=run python scripts/render_debug.py first")
        return 1

    latest = render_files[0]
    url = settings.public_url(f"/renders/{latest.name}")
    print(f"app_base_url={settings.app_base_url}")
    print(f"render_path={latest}")
    print(f"render_url={url}")
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
        print(f"status_code={response.status_code}")
        print(f"content_type={response.headers.get('content-type')}")
        print(f"content_length={len(response.content)}")
        ok = response.status_code == 200 and len(response.content) > 1000
    except Exception as exc:
        print(f"error={exc}")
        ok = False

    print(f"PUBLIC_ASSET_CHECK={'true' if ok else 'false'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
