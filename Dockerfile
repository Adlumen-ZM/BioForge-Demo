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

# 当前镜像定位为环境镜像（environment image），不包含业务代码
# 业务代码由使用者自行挂载或通过其他方式提供

# 创建必要目录
RUN mkdir -p /app/data /app/v0_1PDF /app/v0_1results

# 设置默认环境变量
ENV BIZ_DB_PATH=/app/data/hap_v01.db
ENV TRACE_DB_PATH=/app/data/hap_trace.db
ENV PYTHONUNBUFFERED=1

# 默认启动命令（环境镜像，进入 Python 交互模式）
CMD ["python"]
