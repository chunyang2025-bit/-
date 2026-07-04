from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SpaceType(str, Enum):
    bedroom = "卧室"
    living_room = "客厅"
    kitchen = "厨房"
    balcony = "阳台"
    whole_small_home = "整屋小户型"


class HouseProperty(str, Enum):
    rental = "租房"
    owned = "自住"


class DecorStyle(str, Enum):
    cream = "奶油风"
    minimalist = "极简"
    wood = "原木"
    french = "法式"
    modern = "现代"


class VideoFocus(str, Enum):
    storage = "收纳改造"
    affordable = "平价软装"
    atmosphere = "氛围感提升"
    minimal_saving = "极简省钱"


class GenerateRequest(BaseModel):
    space_type: SpaceType
    house_property: HouseProperty
    decor_style: DecorStyle
    area_sqm: float = Field(gt=0, le=500)
    budget_min: int = Field(ge=0)
    budget_max: int = Field(gt=0)
    video_focus: VideoFocus

    @field_validator("budget_max")
    @classmethod
    def budget_range_ok(cls, value: int, info):
        budget_min = info.data.get("budget_min")
        if budget_min is not None and value < budget_min:
            raise ValueError("最高预算必须大于或等于最低预算")
        return value


class DesignItem(BaseModel):
    name: str
    material: str
    size: str
    scene: str
    taobao_keyword: str
    suggested_price_min: int
    suggested_price_max: int
    role: str


class DesignPlan(BaseModel):
    title: str
    concept_summary: str
    style_description: str
    target_users: str
    items: List[DesignItem] = Field(min_length=3)
    compliance_note: str = "AI 设计方案仅供参考，商品价格以淘宝官方实时页面为准。"
    generated_by: str = "demo"


class Product(BaseModel):
    item_id: str
    title: str
    price: float
    original_price: Optional[float] = None
    coupon_price: Optional[float] = None
    image_url: Optional[str] = None
    item_url: str
    shop_name: str
    commission_rate: float = 0
    sales: int = 0
    source: str = "淘宝"
    is_realtime: bool = False

    @property
    def final_price(self) -> float:
        return self.coupon_price or self.price


class ProductMatch(BaseModel):
    design_item: DesignItem
    products: List[Product]


class ProductSearchRequest(BaseModel):
    design_plan: DesignPlan
    budget_min: int = Field(ge=0)
    budget_max: int = Field(gt=0)


class ProductSearchResponse(BaseModel):
    matches: List[ProductMatch]
    realtime: bool
    source_note: str


class BudgetLine(BaseModel):
    item_name: str
    selected_product: Product
    design_role: str


class BudgetPlan(BaseModel):
    name: str
    target_user: str
    lines: List[BudgetLine]
    total_price: float
    note: str


class BudgetResponse(BaseModel):
    low_plan: BudgetPlan
    high_plan: BudgetPlan
    difference_summary: str


class GenerateVideoRequest(BaseModel):
    input: GenerateRequest
    design_plan: DesignPlan
    product_matches: List[ProductMatch]
    budget: BudgetResponse
    render: Optional["RenderedAsset"] = None


class GeneratedVideo(BaseModel):
    video_url: str
    video_path: str
    duration_seconds: float
    compliance_caption: str


class RenderedClip(BaseModel):
    title: str
    kind: str
    video_url: str
    video_path: str
    task_id: Optional[str] = None
    duration_seconds: float = 5


class RenderedAsset(BaseModel):
    render_url: str
    render_path: str
    prompt: str
    provider: str
    is_demo: bool = True
    render_type: str = "image"
    render_video_url: Optional[str] = None
    render_video_path: Optional[str] = None
    render_task_id: Optional[str] = None
    render_video_duration_seconds: Optional[float] = None
    render_clips: List[RenderedClip] = Field(default_factory=list)


class TemplateGenerateRequest(GenerateRequest):
    template_keys: List[str] = Field(default_factory=list)


class StyleTemplate(BaseModel):
    key: str
    label: str
    decor_style: str
    space_type: str
    house_property: str
    video_focus: str
    video_url: str
    video_path: str
    cached: bool = True
    task_id: Optional[str] = None
    duration_seconds: float = 5
    updated_at: Optional[str] = None


class TemplateLibraryResponse(BaseModel):
    templates: List[StyleTemplate]


class ExportExcelRequest(BaseModel):
    design_plan: DesignPlan
    product_matches: List[ProductMatch]
    budget: BudgetResponse


class ExportExcelResponse(BaseModel):
    excel_url: str
    excel_path: str


class PublishCopy(BaseModel):
    platform: str
    title: str
    body: str
    hashtags: List[str]


class FullPipelineResponse(BaseModel):
    request: GenerateRequest
    design_plan: DesignPlan
    render: RenderedAsset
    products: ProductSearchResponse
    budget: BudgetResponse
    video: GeneratedVideo
    excel: ExportExcelResponse
    publish_copies: List[PublishCopy]
    warnings: List[str] = []
