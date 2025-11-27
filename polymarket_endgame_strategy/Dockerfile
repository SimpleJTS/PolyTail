# Polymarket 尾盘交易策略
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=UTC \
    LOG_DIR=/app/logs

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 验证关键库已安装
RUN python3 -c "from py_clob_client.client import ClobClient; print('✅ py-clob-client OK')"

COPY . .

# 创建日志目录
RUN mkdir -p /app/logs

# 日志卷
VOLUME ["/app/logs"]

# 启动时验证配置
ENTRYPOINT ["python3", "main.py"]
