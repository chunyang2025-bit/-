import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.models import DecorStyle, GenerateRequest, HouseProperty, SpaceType, VideoFocus
from services.design_service import DesignService
from services.render_service import RenderService


async def main() -> int:
    settings = get_settings()
    request = GenerateRequest(
        space_type=SpaceType.living_room,
        house_property=HouseProperty.rental,
        decor_style=DecorStyle.cream,
        area_sqm=38,
        budget_min=3000,
        budget_max=9000,
        video_focus=VideoFocus.affordable,
    )
    plan = await DesignService(settings).generate(request)
    render = await RenderService(settings).generate(request, plan)
    print("RENDER_OK")
    print(f"provider={render.provider}")
    print(f"is_demo={render.is_demo}")
    print(f"render={render.render_path}")
    print(f"prompt={render.prompt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
