#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is missing. Install it first: sudo apt install -y ffmpeg"
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

if ! python -m pip install --no-cache-dir --timeout 120 -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt; then
  python -m pip install --no-cache-dir --timeout 120 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

python scripts/check_config.py
python scripts/smoke_test.py
