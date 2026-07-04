import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


def status(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def main() -> int:
    settings = get_settings()
    checks = {
        "env_file": (PROJECT_ROOT / ".env").exists(),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "openai_api_key": settings.has_openai,
        "openai_model": bool((settings.openai_model or "").strip()),
        "openai_base_url": bool((settings.openai_base_url or "").strip()),
        "app_base_url_public": settings.app_base_url.startswith("http://") or settings.app_base_url.startswith("https://"),
        "tts_available": settings.has_tts,
        "tbk_app_key": bool(settings.tbk_app_key),
        "tbk_app_secret": bool(settings.tbk_app_secret),
        "tbk_adzone_id": bool(settings.tbk_adzone_id),
        "render_video_ready": bool(
            (settings.render_provider or "").lower() == "kling"
            and (settings.render_kind or "").lower() == "video"
            and settings.render_api_url
            and settings.render_api_key
        ),
        "storage_writable": _writable(settings.tmp_dir),
    }

    print("CONFIG_CHECK")
    for name, ok in checks.items():
        print(f"{name}={status(ok)}")

    required_for_demo = ["env_file", "ffmpeg", "storage_writable"]
    required_for_production = required_for_demo + [
        "openai_api_key",
        "openai_model",
        "openai_base_url",
        "tbk_app_key",
        "tbk_app_secret",
        "tbk_adzone_id",
    ]
    missing_demo = [name for name in required_for_demo if not checks[name]]
    missing_prod = [name for name in required_for_production if not checks[name]]

    if missing_demo:
        print("DEMO_READY=false")
        print("missing_demo=" + ",".join(missing_demo))
        return 1

    print("DEMO_READY=true")
    if missing_prod:
        print("PRODUCTION_READY=false")
        print("missing_production=" + ",".join(missing_prod))
        return 0

    print("PRODUCTION_READY=true")
    return 0


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
