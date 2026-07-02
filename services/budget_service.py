from typing import List

from app.models import BudgetLine, BudgetPlan, BudgetResponse, ProductMatch


class BudgetService:
    def calculate(self, matches: List[ProductMatch]) -> BudgetResponse:
        low_lines = []
        high_lines = []
        for match in matches:
            products = sorted(match.products, key=lambda product: product.final_price)
            if not products:
                continue
            low_product = products[0]
            high_product = products[-1]
            low_lines.append(
                BudgetLine(item_name=match.design_item.name, selected_product=low_product, design_role=match.design_item.role)
            )
            high_lines.append(
                BudgetLine(item_name=match.design_item.name, selected_product=high_product, design_role=match.design_item.role)
            )
        low_total = round(sum(line.selected_product.final_price for line in low_lines), 2)
        high_total = round(sum(line.selected_product.final_price for line in high_lines), 2)
        return BudgetResponse(
            low_plan=BudgetPlan(
                name="低配平价版",
                target_user="租房党 / 快速起号内容",
                lines=low_lines,
                total_price=low_total,
                note="优先选择每个单品中价格最低且销量、佣金达标的商品。",
            ),
            high_plan=BudgetPlan(
                name="高配质感版",
                target_user="自住党 / 品质种草内容",
                lines=high_lines,
                total_price=high_total,
                note="优先选择同组候选中价格更高、质感表达更强的商品。",
            ),
            difference_summary=f"高配版比低配版约高 {round(high_total - low_total, 2)} 元，主要差异来自材质、尺寸和店铺定位。",
        )
