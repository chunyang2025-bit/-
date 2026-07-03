# 部署说明

本文档面向已有备案域名、HTTPS 入口和企业服务器的部署场景。

## 1. 准备环境

建议环境：

- Python 3.11+
- FFmpeg
- Nginx
- systemd
- 已备案域名和 HTTPS 证书

安装 FFmpeg：

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg python3-venv
```

## 2. 部署代码

```bash
git clone <your-repo-url> ai-home-video
cd ai-home-video
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，至少配置：

```env
APP_ENV=production
APP_BASE_URL=https://your-domain.com
SECRET_KEY=replace-with-a-long-random-secret
OPENAI_API_KEY=replace-me
OPENAI_MODEL=replace-with-approved-model
TBK_APP_KEY=replace-me
TBK_APP_SECRET=replace-me
TBK_ADZONE_ID=replace-me
```

首次部署也可以直接运行项目内脚本，它会安装 Python 依赖、创建 `.env`、执行配置检查和 smoke 测试：

```bash
bash scripts/server_setup.sh
```

## 3. 启动服务

本机验证：

```bash
bash scripts/run_server.sh
```

systemd 示例：

```ini
[Unit]
Description=AI Home Video FastAPI
After=network.target

[Service]
User=www-data
WorkingDirectory=/srv/ai-home-video
EnvironmentFile=/srv/ai-home-video/.env
ExecStart=/srv/ai-home-video/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 4. Nginx HTTPS 反向代理

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

## 5. 上线检查

```bash
curl -s https://your-domain.com/api/health
```

确认返回：

- `ok: true`
- `openai_configured: true`
- `tbk_configured: true`
- `ffmpeg_available: true`

运行一键生成 smoke 测试：

```bash
source .venv/bin/activate
python scripts/smoke_test.py
```

同时手动生成一条视频，检查：

- 商品链接可打开淘宝官方页面。
- 视频全程有 AI 生成与价格参考声明。
- Excel 包含商品名、券后价、佣金、淘宝直达链接。
- `storage/logs` 有 API 调用日志。
