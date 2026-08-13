#!/usr/bin/env bash
# 一键部署到阿里云轻量应用服务器 / ECS (Docker + 公网 WebUI)
# 通用要求 §五.9: 线上部署 URL，必须提供可访问的 WebUI 接口。
# 前提: 阿里云账号 + 一台运行 Docker 的轻量服务器/ECS。
# 用法: 先编辑下方变量(或通过环境变量传入),再执行本脚本。
set -euo pipefail

# ====== 填写你的阿里云服务器信息 ======
SERVER_HOST="${ALIYUN_HOST:-}"       # 服务器公网 IP 或域名,如 47.96.x.x
SERVER_USER="${ALIYUN_USER:-root}"   # SSH 用户
IMAGE_NAME="${DOCKER_IMAGE:-coding-agent-harness}"

if [ -z "$SERVER_HOST" ]; then
  echo "请先设置 ALIYUN_HOST 环境变量或编辑脚本中的 SERVER_HOST。"
  echo "例如: export ALIYUN_HOST=47.96.x.x"
  exit 1
fi

echo "==> 1. 本地构建 Docker 镜像..."
docker build -t "$IMAGE_NAME" .

echo "==> 2. 推送到阿里云容器镜像服务(ACR)..."
# 如果已配 ACR,取消下面注释:
# ACR_REGISTRY="${ALIYUN_REGISTRY:-registry.cn-hangzhou.aliyuncs.com}"
# ACR_NAMESPACE="${ALIYUN_NAMESPACE:-}"
# docker tag "$IMAGE_NAME" "$ACR_REGISTRY/$ACR_NAMESPACE/$IMAGE_NAME:latest"
# docker push "$ACR_REGISTRY/$ACR_NAMESPACE/$IMAGE_NAME:latest"

echo "==> 3. 上传镜像到服务器(通过 SSH + docker save/load)..."
docker save "$IMAGE_NAME" | gzip | ssh "$SERVER_USER@$SERVER_HOST" "gunzip | docker load"

echo "==> 4. 重启容器..."
ssh "$SERVER_USER@$SERVER_HOST" <<'ENDSSH'
  set -e
  IMG="coding-agent-harness"
  # 停旧容器
  docker stop "$IMG" 2>/dev/null || true
  docker rm "$IMG" 2>/dev/null || true
  # 启动(mock 模式,无需 key;真实 LLM 经 WebUI 凭据端点录入)
  docker run -d --name "$IMG" \
    --restart=unless-stopped \
    -p 80:8000 \
    "$IMG"
  echo "==> 容器已启动,等待就绪..."
  sleep 3
  docker ps --filter "name=$IMG"
  echo ""
  echo "==> 健康检查..."
  curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:8000/ || true
  echo ""
ENDSSH

echo ""
echo "==> 部署完成!"
echo "    公网地址: http://$SERVER_HOST"
echo "    将上述 URL 填入 README 的「部署架构」章节(§五.9 硬要求)。"
