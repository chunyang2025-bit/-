import json
import re
from typing import Any, Dict

import httpx

from app.config import Settings
from app.models import DesignItem, DesignPlan, GenerateRequest


DESIGN_SCHEMA: Dict[str, Any] = {
    "name": "home_design_plan",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "concept_summary", "style_description", "target_users", "items"],
        "properties": {
            "title": {"type": "string"},
            "concept_summary": {"type": "string"},
            "style_description": {"type": "string"},
            "target_users": {"type": "string"},
            "items": {
                "type": "array",
                "minItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "name",
                        "material",
                        "size",
                        "scene",
                        "taobao_keyword",
                        "suggested_price_min",
                        "suggested_price_max",
                        "role",
                    ],
                    "properties": {
                        "name": {"type": "string"},
                        "material": {"type": "string"},
                        "size": {"type": "string"},
                        "scene": {"type": "string"},
                        "taobao_keyword": {"type": "string"},
                        "suggested_price_min": {"type": "integer"},
                        "suggested_price_max": {"type": "integer"},
                        "role": {"type": "string"},
                    },
                },
            },
        },
    },
    "strict": True,
}


class DesignService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(self, request: GenerateRequest) -> DesignPlan:
        if self.settings.has_openai:
            try:
                return await self._generate_with_openai(request)
            except Exception:
                return self._demo_plan(request, generated_by="demo-openai-fallback")
        return self._demo_plan(request, generated_by="demo")

    async def _generate_with_openai(self, request: GenerateRequest) -> DesignPlan:
        model = self.settings.openai_model or "gpt-4.1-mini"
        prompt = f"""
你是 MCN 家装短视频选品策划。请根据输入生成可落地软装方案，只输出严格 JSON。
硬性要求：
1. 每个 taobao_keyword 必须包含风格、尺寸、材质、场景。
2. 禁止泛泛描述，必须可用于淘宝联盟实时商品搜索。
3. 单品数量 6-8 个，覆盖空间核心功能、氛围、收纳。

输入：
空间类型：{request.space_type}
房屋属性：{request.house_property}
装修风格：{request.decor_style}
面积：{request.area_sqm}㎡
预算：{request.budget_min}-{request.budget_max} 元
视频侧重点：{request.video_focus}
"""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你只生成严格 JSON，不输出 Markdown，不输出解释文字。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.5,
        }
        if self.settings.is_deepseek:
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["response_format"] = {"type": "json_schema", "json_schema": DESIGN_SCHEMA}
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        async with httpx.AsyncClient(base_url=self.settings.openai_base_url, timeout=45) as client:
            response = await client.post("/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        plan = DesignPlan.model_validate(self._load_json(content))
        plan.generated_by = "deepseek" if self.settings.is_deepseek else "openai"
        return self._normalize_keywords(plan, request)

    def _demo_plan(self, request: GenerateRequest, generated_by: str) -> DesignPlan:
        style = request.decor_style.value
        scene = request.space_type.value
        scale = "小户型" if request.area_sqm <= 60 else "改善型"
        item_specs = [
            ("模块沙发", "科技布", "180cm", "客厅", 1200, 2600, "提供主要坐卧区，控制占地面积"),
            ("收纳茶几", "橡胶木", "80cm", "客厅", 260, 680, "兼顾置物和隐藏收纳"),
            ("落地灯", "原木+亚克力", "120cm", "卧室", 120, 360, "补足氛围光，提升视频画面层次"),
            ("窗帘", "棉麻遮光", "2.5m高", scene, 180, 520, "统一软装色系并遮挡杂乱背景"),
            ("地毯", "短绒", "160x230cm", "客厅", 220, 780, "划分区域并提升温暖感"),
            ("置物架", "碳钢+木板", "60cm宽", scene, 160, 420, "增强垂直收纳，适合租房免打孔"),
        ]
        if request.video_focus == "收纳改造":
            item_specs.append(("抽屉收纳柜", "PP+木面", "40cm宽", scene, 150, 360, "低成本隐藏零碎物品"))
        elif request.video_focus == "氛围感提升":
            item_specs.append(("装饰画组合", "油画布", "40x60cm", scene, 90, 260, "形成视觉焦点和风格记忆点"))
        else:
            item_specs.append(("可移动边几", "金属+岩板", "45cm", scene, 120, 320, "低价补足随手置物需求"))

        items = [
            DesignItem(
                name=name,
                material=material,
                size=size,
                scene=item_scene,
                taobao_keyword=f"{style}{material} {size} {item_scene}{name}",
                suggested_price_min=low,
                suggested_price_max=high,
                role=role,
            )
            for name, material, size, item_scene, low, high, role in item_specs
        ]
        return DesignPlan(
            title=f"{request.area_sqm:g}㎡{style}{scale}{request.video_focus.value}方案",
            concept_summary=f"以可购买软装替代重施工，用统一材质、低饱和色和可移动收纳完成 {scene} 快速改造。",
            style_description=f"{style}强调材质统一、色彩克制和空间留白，适合批量内容中展示真实可买的改造路径。",
            target_users="MCN 家居内容运营、租房党、自住预算有限的年轻家庭",
            items=items,
            generated_by=generated_by,
        )

    @staticmethod
    def _normalize_keywords(plan: DesignPlan, request: GenerateRequest) -> DesignPlan:
        normalized = []
        for item in plan.items:
            keyword = item.taobao_keyword
            for token in [request.decor_style.value, item.size, item.material, item.scene]:
                if token and token not in keyword:
                    keyword = f"{token} {keyword}"
            item.taobao_keyword = " ".join(keyword.split())
            normalized.append(item)
        plan.items = normalized
        return plan

    @staticmethod
    def _load_json(content: str) -> Dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
