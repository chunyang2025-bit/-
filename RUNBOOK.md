# 运营 Runbook

## 日常生成流程

1. 打开内部工具页面。
2. 选择空间类型、房屋属性、装修风格、面积、预算和视频侧重点。
3. 点击“一键生成 AI 家装方案 + 视频”。
4. 预览视频，下载采购 Excel。
5. 复制抖音 / 小红书 / 视频号文案。
6. 人工复核商品链接和价格后发布。

## 常见问题

### 生成结果提示演示数据

说明服务器没有配置完整 TBK 凭证。上线内容不得使用演示数据。

### 视频为空或生成失败

检查服务器是否安装 FFmpeg：

```bash
ffmpeg -version
```

同时检查 `storage/logs` 的最新日志。

可在服务器上运行：

```bash
python scripts/smoke_test.py
```

### 商品数量不足

可调整：

- `TBK_MIN_COMMISSION_RATE`
- `TBK_MIN_SALES`
- 预算上限
- GPT 生成的关键词策略

### 请求被限流

调整：

```env
RATE_LIMIT_PER_MINUTE=60
```

生产环境建议在 Nginx 层同时配置限流。
