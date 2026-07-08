# AI 家装方案・真实商品溯源・一键视频生成系统

面向 MCN 内部运营的自动化家装短视频生产工具。运营输入户型、风格、预算和视频侧重点后，系统自动生成结构化软装方案、淘宝联盟商品匹配、低配/高配预算、短视频、采购 Excel 和三平台发布文案。

## 已实现能力

- FastAPI 后端与单页运营前端。
- `/api/generate_design`：结构化软装方案生成，强制输出商品搜索关键词。
- `/api/search_products`：淘宝联盟 TBK 签名、鉴权、批量查询与过滤逻辑。
- `/api/calc_budget`：低配平价版与高配质感版预算计算。
- `/api/generate_video`：非数字人视频合成，含字幕卡片、价格卡片、来源与 AI 声明。
- `/api/generate_render`：生成装修效果图资产。默认本地生成演示效果图，后续可替换为可灵、即梦、通义万相等图像/视频生成服务。
- 视频逐品页会嵌入淘宝联盟返回的官方商品图；没有真实商品图时会明确显示占位状态。
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
python scripts/check_config.py
python scripts/smoke_test.py
```

`smoke_test.py` 会输出 `realtime_products` 和 `product_images`。上线发布前这两个数应大于 0，否则说明 TBK 没有返回真实可展示商品图或接口已回退演示数据。

淘宝客物料权限审核期间，系统会使用明确标注的“虚拟商品演示”数据生成视频，便于演示端到端流程；该模式不可作为真实商品种草内容发布。

当前装修效果图默认为本地生成的演示效果图，用于展示视频结构和空间氛围。配置可灵文生视频后，系统会先生成一段真实 AI 家装动态素材，并自动接入最终 MP4 开场。

可灵文生视频配置示例：

```env
RENDER_PROVIDER=kling
RENDER_KIND=video
RENDER_API_URL=https://api-beijing.klingai.com
RENDER_API_KEY=api-key-kling-xxxx
RENDER_API_SECRET=
RENDER_AUTH_HEADER=Authorization
RENDER_AUTH_PREFIX=Bearer
RENDER_VIDEO_ENDPOINT=/text-to-video/kling-3.0-turbo
RENDER_TASK_ENDPOINT=/tasks
RENDER_RESOLUTION=720p
RENDER_ASPECT_RATIO=9:16
RENDER_DURATION=5
RENDER_POLL_SECONDS=180
```

配置后可先运行 `python scripts/render_debug.py` 单独测试。输出 `provider=kling-video`、`render_type=video`、`render_video=...mp4`，说明已走通可灵视频接口。

默认启用模板模式：系统会按装修风格生成并缓存一条完整风格模板视频；成片时先介绍“多少平米小家 + 什么装修风格”，再在同一套完整风格模板上逐个叠加商品名、材质、尺寸、价格和来源浮层。可通过 `RENDER_PRODUCT_CLIP_COUNT` 控制单次参与成片的商品数量，通过 `RENDER_REUSE_TEMPLATES=true` 复用已生成模板，减少可灵消耗。

如果后续使用图生视频或把装修图传给国内平台，必须确保图片 URL 可公网访问。请将 `APP_BASE_URL` 配成公网域名或公网 IP，例如：

```env
APP_BASE_URL=http://47.97.11.125:8000
```

然后运行：

```bash
python scripts/public_asset_debug.py
```

返回 `PUBLIC_ASSET_CHECK=true` 后，才能把 `/renders/...` 图片 URL 传给可灵等平台。

如 TBK 报 `Invalid signature`，先运行：

```bash
python scripts/tbk_debug.py
```

重点检查 `.env` 中 `TBK_APP_SECRET` 是否复制错误、包含空格、或与 `TBK_APP_KEY` 不匹配。

淘宝客关键词搜索请使用新版接口：

```env
TBK_SEARCH_METHOD=taobao.tbk.dg.material.optional.upgrade
TBK_PID=mm_xxxxxxxxxx_xxxxxxxxxx_xxxxxxxxxx
TBK_ADZONE_ID=
TBK_SITE_ID=
TBK_MATERIAL_ID=31362
```

系统会从完整 `TBK_PID` 自动拆出 `site_id` 和 `adzone_id`；也可以继续手动填写 `TBK_SITE_ID` / `TBK_ADZONE_ID`。如升级版接口暂不可用，系统会自动回退到 `taobao.tbk.dg.material.recommend`，保证链路不中断。

Ubuntu 服务器可直接运行：

```bash
bash scripts/server_setup.sh
```

## 关键环境变量

- `OPENAI_API_KEY`：GPT 结构化方案与可选配音。
- `OPENAI_MODEL`：结构化方案模型，建议按企业账号可用模型配置。
- `OPENAI_TTS_MODEL`：配音模型，留空时使用代码默认值。
- `OPENAI_BASE_URL`：兼容 OpenAI Chat Completions 的服务地址。使用 DeepSeek 时填 `https://api.deepseek.com/v1`，`OPENAI_MODEL=deepseek-chat`。
- `TBK_APP_KEY` / `TBK_APP_SECRET` / `TBK_PID`：淘宝联盟 TOP/TBK 必填凭证。`TBK_PID` 支持完整三段式 `mm_..._..._...`，系统会自动解析推广位。
- `TBK_SEARCH_METHOD`：默认 `taobao.tbk.dg.material.optional.upgrade`，旧版 `taobao.tbk.dg.material.optional` 已下线。
- `TBK_MATERIAL_ID`：官方物料 ID，请使用淘宝联盟官方物料 ID，不要填写资源包、订单或后台页面 ID。
- `TBK_PAGE_SIZE` / `TBK_PAGE_COUNT`：关键词搜索候选池大小，默认每个物料池最多取 `100 * 3` 个候选，找到合格商品会提前停止。
- `TBK_MIN_COMMISSION_RATE`：最低佣金比例，默认 `1000`，即 10%。
- `TBK_MIN_SALES`：最低销量过滤阈值。
- `RATE_LIMIT_PER_MINUTE`：单 IP 每分钟 API 调用限制。
- `LOG_RETENTION_DAYS`：合规日志保留天数，默认 180 天。

## 合规说明

使用 DeepSeek 等兼容接口时，系统会用于结构化方案生成；当前配音仍需支持 `/audio/speech` 的服务，DeepSeek 配置下会自动跳过配音并生成无旁白视频。

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
