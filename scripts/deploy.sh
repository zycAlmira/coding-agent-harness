#!/usr/bin/env sh
# 一键部署到 Fly.io(通用 §4.11)
# 前提:已 `flyctl auth login`,首次需先 `flyctl apps create coding-agent-harness-ai4se`
# 产生公网 URL 后,填入 README 的"线上部署"章节(§五.9 硬要求)。
set -e

echo "==> 构建并部署到 Fly.io(rolling)..."
flyctl deploy --strategy=rolling

echo "==> 部署完成。公网地址:"
flyctl status
echo ""
echo "==> 将上面的 hostname(形如 *.fly.dev)填入 README 的线上部署章节。"
