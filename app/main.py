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
)
from app.rate_limit import InMemoryRateLimiter
from services.budget_service import BudgetService
from services.copy_service import CopyService
from services.design_service import DesignService
from services.excel_service import ExcelService
from services.logging_service import ComplianceLogger
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


@app.post("/api/calc_budget", response_model=BudgetResponse, dependencies=[Depends(limited)])
async def calc_budget(payload: ProductSearchResponse) -> BudgetResponse:
    budget = budget_service.calculate(payload.matches)
    logger.write("budget_calculated", {"low": budget.low_plan.total_price, "high": budget.high_plan.total_price})
    return budget


@app.post("/api/generate_video", response_model=GeneratedVideo, dependencies=[Depends(limited)])
async def generate_video(payload: GenerateVideoRequest) -> GeneratedVideo:
    video = await video_service.generate(payload.input, payload.design_plan, payload.product_matches, payload.budget)
    logger.write("video_generated", {"video_path": video.video_path, "duration": video.duration_seconds})
    return video


@app.post("/api/export_excel", response_model=ExportExcelResponse, dependencies=[Depends(limited)])
async def export_excel(payload: ExportExcelRequest) -> ExportExcelResponse:
    path = excel_service.export(payload.design_plan, payload.product_matches, payload.budget)
    logger.write("excel_exported", {"excel_path": str(path)})
    return ExportExcelResponse(excel_url=f"/exports/{Path(path).name}", excel_path=str(path))


@app.post("/api/run_full_pipeline", response_model=FullPipelineResponse, dependencies=[Depends(limited)])
async def run_full_pipeline(payload: GenerateRequest) -> FullPipelineResponse:
    warnings = []
    design_plan = await design_service.generate(payload)
    matches = await tbk_service.search_matches(design_plan.items, payload.budget_max)
    realtime = bool(matches and all(product.is_realtime for match in matches for product in match.products))
    if not realtime:
        warnings.append("当前未配置完整 TBK 凭证，商品为演示数据；上线前必须配置淘宝联盟实时 API。")
    if not settings.has_openai:
        warnings.append("当前未配置 OpenAI API Key，设计方案为本地确定性演示生成。")

    products = ProductSearchResponse(
        matches=matches,
        realtime=realtime,
        source_note="淘宝联盟 TBK 实时商品" if realtime else "演示商品数据；配置 TBK 后自动切换为实时商品",
    )
    budget = budget_service.calculate(matches)
    video = await video_service.generate(payload, design_plan, matches, budget)
    excel_path = excel_service.export(design_plan, matches, budget)
    excel = ExportExcelResponse(excel_url=f"/exports/{excel_path.name}", excel_path=str(excel_path))
    copies = copy_service.build_publish_copies(payload, design_plan, budget)
    logger.write(
        "full_pipeline_completed",
        {
            "title": design_plan.title,
            "realtime_products": realtime,
            "video_path": video.video_path,
            "excel_path": excel.excel_path,
        },
    )
    return FullPipelineResponse(
        request=payload,
        design_plan=design_plan,
        products=products,
        budget=budget,
        video=video,
        excel=excel,
        publish_copies=copies,
        warnings=warnings,
    )
