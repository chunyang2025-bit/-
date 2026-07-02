# AI 家装方案・真实商品溯源・一键视频生成系统

面向 MCN 内部运营的自动化家装短视频生产工具。运营输入户型、风格、预算和视频侧重点后，系统自动生成结构化软装方案、淘宝联盟商品匹配、低配/高配预算、短视频、采购 Excel 和三平台发布文案。

## 已实现能力

- FastAPI 后端与单页运营前端。
- `/api/generate_design`：结构化软装方案生成，强制输出商品搜索关键词。
- `/api/search_products`：淘宝联盟 TBK 签名、鉴权、批量查询与过滤逻辑。
- `/api/calc_budget`：低配平价版与高配质感版预算计算。
- `/api/generate_video`：非数字人视频合成，含字幕卡片、价格卡片、来源与 AI 声明。
- `/api/export_excel`：采购清单 Excel 导出。
- `/api/run_full_pipeline`：前端一键串完整流程。
- 合规日志、基础限流、静态产物下载、演示降级数据。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

没有配置 OpenAI / TBK 密钥时，系统会使用确定性的演示方案和演示商品跑通完整链路。上线前必须配置真实企业 API 密钥，确保商品、价格、链接和佣金来自实时官方接口。

## 本地验收

安装依赖后可运行 smoke 测试，脚本会调用一键全流程并确认 MP4 与 Excel 实际落盘：

```bash
python scripts/smoke_test.py
```

## 关键环境变量

- `OPENAI_API_KEY`：GPT 结构化方案与可选配音。
- `OPENAI_MODEL`：结构化方案模型，建议按企业账号可用模型配置。
- `OPENAI_TTS_MODEL`：配音模型，留空时使用代码默认值。
- `TBK_APP_KEY` / `TBK_APP_SECRET` / `TBK_ADZONE_ID`：淘宝联盟 TOP/TBK 必填凭证。
- `TBK_MIN_COMMISSION_RATE`：最低佣金比例，默认 `1000`，即 10%。
- `TBK_MIN_SALES`：最低销量过滤阈值。
- `RATE_LIMIT_PER_MINUTE`：单 IP 每分钟 API 调用限制。
- `LOG_RETENTION_DAYS`：合规日志保留天数，默认 180 天。

## 合规说明

系统固定不做数字人出镜，不做爬虫缓存，不做自动发布。视频与 Excel 会标注：

- AI 设计方案仅供参考。
- 商品来源为淘宝官方在售商品。
- 价格为实时券后价，以官网为准。
- 本内容由 AI 自动生成。

API 调用日志写入 `storage/logs/api-YYYY-MM.jsonl`，默认保留不少于 180 天。

## 项目结构

```text
app/                 FastAPI 入口、配置、模型、限流
services/            GPT、TBK、预算、视频、Excel、文案和日志服务
static/              单页运营前端
storage/             日志、导出、视频和临时文件目录
requirements.txt     Python 依赖
.env.example         环境变量样例
DEPLOYMENT.md        企业服务器部署说明
API.md               接口说明
COMPLIANCE.md        合规与上线检查
```
