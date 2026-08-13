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

# 多语言工具链:Java 17 + Maven(清华源下载预编译二进制,避免 apt 包名/源
# 问题)。agent 可修改并测试 Java 项目。
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://mirrors.tuna.tsinghua.edu.cn/Adoptium/17/jdk/x64/linux/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20_8.tar.gz', '/tmp/jdk.tar.gz')" \
    && tar xzf /tmp/jdk.tar.gz -C /opt/ && rm /tmp/jdk.tar.gz \
    && mv /opt/jdk-17.0.20+8 /opt/jdk17
ENV JAVA_HOME=/opt/jdk17 \
    PATH=/opt/jdk17/bin:$PATH
# Maven:清华源下载二进制,解压进镜像(slim 无 curl,用 python urllib)
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://mirrors.tuna.tsinghua.edu.cn/apache/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.tar.gz', '/tmp/maven.tar.gz')" \
    && tar xzf /tmp/maven.tar.gz -C /opt/ && rm /tmp/maven.tar.gz \
    && ln -s /opt/apache-maven-3.9.16/bin/mvn /usr/local/bin/mvn \
    # warmup:maven 本地仓库预置(首次 mvn test 下载依赖 ~3 分钟,预跑一次缓存进镜像)
    && mkdir -p /warmup && cd /warmup \
    && printf '<?xml version="1.0"?><project><modelVersion>4.0.0</modelVersion><groupId>w</groupId><artifactId>w</artifactId><version>1</version></project>' > pom.xml \
    && mvn -B -q dependency:resolve 2>/dev/null || true \
    && rm -rf /warmup

# uv:用 pip 安装(避免依赖 ghcr.io——服务器连 GitHub 生态可能不通);
# pip 从阿里云 PyPI 镜像源装(服务器外网到 PyPI 不通,阿里云内网快)。
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

# 先拷依赖锁(利用缓存层:改源码不重装依赖)
COPY pyproject.toml uv.lock ./

# 生产依赖(非 dev extras);--frozen 锁版本可复现;
# 阿里云 PyPI 镜像源(服务器外网到 PyPI 不通)。
RUN uv sync --frozen --no-dev --no-progress \
    --default-index https://mirrors.aliyun.com/pypi/simple/

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
