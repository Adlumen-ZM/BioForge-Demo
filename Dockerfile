# ========== 第一阶段：构建阶段 ==========
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装编译工具和系统依赖
# libmupdf-dev: PyMuPDF / PDF 处理相关依赖
# gcc / g++: 某些 Python 包安装时可能需要编译
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ========== 第二阶段：运行阶段 ==========
FROM python:3.11-slim

WORKDIR /app

# 从构建阶段复制 Python 依赖
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 按 MS 当前版本保留业务代码复制逻辑
# 注意：如果后续我们严格把镜像定位成“纯 environment image”，
# 这里可以再和 MS 讨论是否移除 text_agent / db / run_batch.py 的 COPY。
COPY text_agent/ ./text_agent/
COPY db/ ./db/
COPY run_batch.py .

# 创建必要目录
RUN mkdir -p /app/data /app/v0_1PDF /app/v0_1results

# 设置默认环境变量
ENV BIZ_DB_PATH=/app/data/hap_v01.db
ENV TRACE_DB_PATH=/app/data/hap_trace.db
ENV PYTHONUNBUFFERED=1

# 默认启动命令
CMD ["python", "run_batch.py"]
