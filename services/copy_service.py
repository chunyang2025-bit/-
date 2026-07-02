from typing import List

from app.models import BudgetResponse, DesignPlan, GenerateRequest, PublishCopy


class CopyService:
    def build_publish_copies(self, request: GenerateRequest, plan: DesignPlan, budget: BudgetResponse) -> List[PublishCopy]:
        tags = [request.decor_style.value, request.video_focus.value, "真实可买", "淘宝好物", "AI家装"]
        body = (
            f"{request.area_sqm:g}㎡{request.space_type.value}改造清单来了。"
            f"{plan.concept_summary} 低配约 {budget.low_plan.total_price:.0f} 元，"
            f"高配约 {budget.high_plan.total_price:.0f} 元。价格以淘宝实时页面为准。"
        )
        return [
            PublishCopy(platform="抖音", title=f"{plan.title}｜真实可买", body=body, hashtags=tags + ["家居改造"]),
            PublishCopy(platform="小红书", title=f"{request.decor_style.value}{request.space_type.value}软装清单", body=body, hashtags=tags + ["租房改造"]),
            PublishCopy(platform="视频号", title=f"{plan.title}", body=body, hashtags=tags + ["软装搭配"]),
        ]
