# API 文档

Base URL：`https://your-domain.com`

## POST `/api/generate_design`

生成结构化软装方案。

请求体：

```json
{
  "space_type": "客厅",
  "house_property": "租房",
  "decor_style": "奶油风",
  "area_sqm": 38,
  "budget_min": 3000,
  "budget_max": 9000,
  "video_focus": "平价软装"
}
```

返回包含方案标题、设计理念、风格说明、适合人群和单品数组。每个单品包含材质、尺寸、场景、淘宝搜索关键词、建议单价区间和搭配作用。

## POST `/api/search_products`

批量匹配淘宝联盟商品。

请求体：

```json
{
  "design_plan": {},
  "budget_min": 3000,
  "budget_max": 9000
}
```

返回每个设计单品的最优 3 个商品候选，包含券后价、原价、图片、链接、店铺、佣金比例、销量和来源。

## POST `/api/calc_budget`

根据商品候选计算低配与高配预算。

请求体为 `/api/search_products` 的返回结构。

## POST `/api/generate_video`

生成 40-60 秒竖版短视频。

请求体包含原始输入、设计方案、商品匹配和预算结果。

## POST `/api/export_excel`

导出采购 Excel。

请求体包含设计方案、商品匹配和预算结果。

## POST `/api/run_full_pipeline`

前端一键接口，串联设计、商品匹配、预算、视频、Excel 和发布文案。

请求体与 `/api/generate_design` 相同。

返回：

- `design_plan`
- `products`
- `budget`
- `video`
- `excel`
- `publish_copies`
- `warnings`

## GET `/api/health`

健康检查与关键 API 配置状态，包含 OpenAI、TBK 和 FFmpeg 是否可用。
