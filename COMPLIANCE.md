# 合规与上线检查

## 强制产品规则

- 不使用数字人出镜。
- 不做 3D 建模渲染。
- 不做用户注册登录。
- 不做自动发布。
- 不做爬虫缓存。
- 商品、价格、链接和佣金必须来自淘宝联盟 TBK 官方实时接口。

## 视频合规声明

生成视频固定包含：

- AI 设计方案仅供参考。
- 商品来源：淘宝官方在售商品。
- 价格为实时券后价，以官网为准。
- 本内容由 AI 自动生成。

## 日志保留

API 事件日志写入：

```text
storage/logs/api-YYYY-MM.jsonl
```

默认保留 `LOG_RETENTION_DAYS=180` 天，用于企业合规审计。生产环境建议将该目录纳入服务器备份策略，但不要提交到 Git。

## 上线前必须确认

- `.env` 已配置真实 `OPENAI_API_KEY`。
- `.env` 已配置真实 `TBK_APP_KEY`、`TBK_APP_SECRET`、`TBK_ADZONE_ID`。
- `/api/health` 返回 `openai_configured=true` 与 `tbk_configured=true`。
- 试跑视频中的商品链接来自淘宝官方可访问页面。
- Excel 中价格、佣金、链接字段完整。
- Nginx 已启用 HTTPS。
- 服务器安装 FFmpeg。
- 运营人员知道价格以淘宝实时页面为准，不可承诺固定价格。
