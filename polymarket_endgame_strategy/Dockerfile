# Polymarket 尾盘交易策略
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=UTC

WORKDIR /app

# 安装依赖
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python3", "main.py"]
