FROM python:3.11-slim

LABEL maintainer="TradingAgents-CN"
LABEL description="TradingAgents-CN Docker Image - AI Trading Agent System"
LABEL version="1.0.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装 Python 依赖
COPY requirements-trimmed.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements-trimmed.txt && \
    pip install "tradingagents @ git+https://github.com/hsliuping/TradingAgents-CN.git" --no-deps 2>/dev/null; \
    echo "Done with deps"

# 复制应用代码
COPY adapter/ /app/adapter/
COPY config/ /app/config/

# 创建必要的目录
RUN mkdir -p /app/logs /app/data

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 默认启动 FastAPI 应用
CMD ["uvicorn", "adapter.main:app", "--host", "0.0.0.0", "--port", "8000"]
