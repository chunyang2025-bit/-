import shutil
from pathlib import Path
from typing import Any, Dict

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, get_settings
from app.models import (
    BudgetResponse,
    DesignPlan,
    ExportExcelRequest,
    ExportExcelResponse,
    FullPipelineResponse,
    GenerateRequest,
    GenerateVideoRequest,
    GeneratedVideo,
    ProductSearchRequest,
    ProductSearchResponse,
    RenderedAsset,
)
from app.rate_limit import InMemoryRateLimiter
from services.budget_service import BudgetService
from services.copy_service import CopyService
from services.design_service import DesignService
from services.excel_service import ExcelService
from services.logging_service import ComplianceLogger
from services.render_service import RenderService
from services.tbk_service import TaobaoTbkService
from services.video_service import VideoService


settings = get_settings()
logger = ComplianceLogger(settings)
rate_limiter = InMemoryRateLimiter(settings.rate_limit_per_minute)

design_service = DesignService(settings)
tbk_service = TaobaoTbkService(settings)
budget_service = BudgetService()
excel_service = ExcelService(settings)
video_service = VideoService(settings)
render_service = RenderService(settings)
copy_service = CopyService()

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")
app.mount("/exports", StaticFiles(directory=settings.exports_dir), name="exports")
app.mount("/videos", StaticFiles(directory=settings.videos_dir), name="videos")
app.mount("/renders", StaticFiles(directory=settings.renders_dir), name="renders")


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        logger.write(
            "api_request",
            {
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "client": request.client.host if request.client else "unknown",
            },
        )
    return response


async def limited(request: Request) -> None:
    await rate_limiter.check(request)


@app.on_event("startup")
async def startup() -> None:
    settings.ensure_dirs()
    logger.cleanup_old_logs()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT_DIR / "static" / "index.html")


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "app": settings.app_name,
        "env": settings.app_env,
        "openai_configured": settings.has_openai,
        "tbk_configured": settings.has_tbk,
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
    }


@app.post("/api/generate_design", response_model=DesignPlan, dependencies=[Depends(limited)])
async def generate_design(payload: GenerateRequest) -> DesignPlan:
    plan = await design_service.generate(payload)
    logger.write("design_generated", {"title": plan.title, "items": len(plan.items), "generated_by": plan.generated_by})
    return plan


@app.post("/api/search_products", response_model=ProductSearchResponse, dependencies=[Depends(limited)])
async def search_products(payload: ProductSearchRequest) -> ProductSearchResponse:
    matches = await tbk_service.search_matches(payload.design_plan.items, payload.budget_max)
    realtime = bool(matches and all(product.is_realtime for match in matches for product in match.products))
    source_note = "淘宝联盟 TBK 实时商品" if realtime else "演示商品数据；配置 TBK 后自动切换为实时商品"
    logger.write(
        "products_matched",
        {"items": len(matches), "realtime": realtime, "products": sum(len(match.products) for match in matches)},
    )
    return ProductSearchResponse(matches=matches, realtime=realtime, source_note=source_note)


@app.post("/api/generate_render", response_model=RenderedAsset, dependencies=[Depends(limited)])
async def generate_render(payload: DesignPlan, request: Request) -> RenderedAsset:
    query = request.query_params
    render_input = GenerateRequest(
        space_type=query.get("space_type", "客厅"),
        house_property=query.get("house_property", "租房"),
        decor_style=query.get("decor_style", "奶油风"),
        area_sqm=float(query.get("area_sqm", 38)),
        budget_min=int(query.get("budget_min", 3000)),
        budget_max=int(query.get("budget_max", 9000)),
        video_focus=query.get("video_focus", "平价软装"),
    )
    render = await render_service.generate(render_input, payload)
    logger.write("render_generated", {"render_path": render.render_path, "provider": render.provider})
    return render


@app.post("/api/calc_budget", response_model=BudgetResponse, dependencies=[Depends(limited)])
async def calc_budget(payload: ProductSearchResponse) -> BudgetResponse:
    budget = budget_service.calculate(payload.matches)
    logger.write("budget_calculated", {"low": budget.low_plan.total_price, "high": budget.high_plan.total_price})
    return budget


@app.post("/api/generate_video", response_model=GeneratedVideo, dependencies=[Depends(limited)])
async def generate_video(payload: GenerateVideoRequest) -> GeneratedVideo:
    video = await video_service.generate(payload.input, payload.design_plan, payload.product_matches, payload.budget, payload.render)
    logger.write("video_generated", {"video_path": video.video_path, "duration": video.duration_seconds})
    return video


@app.post("/api/export_excel", response_model=ExportExcelResponse, dependencies=[Depends(limited)])
async def export_excel(payload: ExportExcelRequest) -> ExportExcelResponse:
    path = excel_service.export(payload.design_plan, payload.product_matches, payload.budget)
    logger.write("excel_exported", {"excel_path": str(path)})
    return ExportExcelResponse(excel_url=settings.public_url(f"/exports/{Path(path).name}"), excel_path=str(path))


@app.post("/api/run_full_pipeline", response_model=FullPipelineResponse, dependencies=[Depends(limited)])
async def run_full_pipeline(payload: GenerateRequest) -> FullPipelineResponse:
    warnings = []
    design_plan = await design_service.generate(payload)
    render = await render_service.generate(payload, design_plan)
    matches = await tbk_service.search_matches(design_plan.items, payload.budget_max)
    realtime = bool(matches and all(product.is_realtime for match in matches for product in match.products))
    if not realtime:
        if settings.has_tbk:
            warnings.append("TBK 已配置，但本次没有匹配到符合条件的实时商品，已回退演示数据。")
        else:
            warnings.append("当前未配置完整 TBK 凭证，商品为演示数据；上线前必须配置淘宝联盟实时 API。")
    if tbk_service.last_errors:
        warnings.extend(tbk_service.last_errors[:5])
    image_count = sum(1 for match in matches for product in match.products if product.image_url)
    if image_count == 0:
        warnings.append("本次商品未获取到官方商品图，视频会显示占位画面；请检查 TBK 返回字段或筛选条件。")
    if not settings.has_openai:
        warnings.append("当前未配置 OpenAI API Key，设计方案为本地确定性演示生成。")

    products = ProductSearchResponse(
        matches=matches,
        realtime=realtime,
        source_note="淘宝联盟 TBK 实时商品" if realtime else "演示商品数据；配置 TBK 后自动切换为实时商品",
    )
    budget = budget_service.calculate(matches)
    video = await video_service.generate(payload, design_plan, matches, budget, render)
    excel_path = excel_service.export(design_plan, matches, budget)
    excel = ExportExcelResponse(excel_url=settings.public_url(f"/exports/{excel_path.name}"), excel_path=str(excel_path))
    copies = copy_service.build_publish_copies(payload, design_plan, budget)
    logger.write(
        "full_pipeline_completed",
        {
            "title": design_plan.title,
            "realtime_products": realtime,
            "video_path": video.video_path,
            "excel_path": excel.excel_path,
            "render_path": render.render_path,
        },
    )
    return FullPipelineResponse(
        request=payload,
        design_plan=design_plan,
        render=render,
        products=products,
        budget=budget,
        video=video,
        excel=excel,
        publish_copies=copies,
        warnings=warnings,
    )
