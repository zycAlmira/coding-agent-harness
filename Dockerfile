# AI4SE Project A Coding Agent Harness — 容器分发
# 通用 §3.2:单条 docker build + 单条 docker run 可启动。
# §3.1:容器不预置任何 LLM key;默认 mock 模式提供可访问 WebUI,
#       真实 LLM 经 WebUI 凭据端点录入(不硬编码)。
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 多语言工具链:Java/Maven(agent 可修改并测试 Java 项目)、Node(可选)。
# 服务器连 GitHub 生态可能不通,故用 apt 装(阿里云 debian 源,通用)。
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jdk-headless maven nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# uv:用 pip 安装(避免依赖 ghcr.io——服务器连 GitHub 生态可能不通);
# pip 从 PyPI 装,更通用。
RUN pip install --no-cache-dir uv

# 先拷依赖锁(利用缓存层:改源码不重装依赖)
COPY pyproject.toml uv.lock ./

# 生产依赖(非 dev extras);--frozen 锁版本可复现
RUN uv sync --frozen --no-dev --no-progress

# 拷源码与配置
COPY src ./src
COPY config.example.yaml ./config.yaml
COPY fixtures ./fixtures

# 控制台脚本 harness 已由 uv sync 装好;默认 mock 模式(无需 key 即可访问 WebUI)
ENV HARNESS_MODE=mock
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/').status==200 else 1)" || exit 1

CMD ["uv", "run", "harness", "serve"]
