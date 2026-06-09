# ========== BioForge 环境镜像 v0.1.3 ==========
#
# 变更说明（相比 0.1.2）：
#   - 新增 sentence-transformers（BGE-M3 嵌入模型依赖）
#   - 构建阶段预下载 BAAI/bge-m3 权重（~1.3 GB），烘焙进镜像，
#     避免每次运行时从 HuggingFace 下载
#   - HF_HOME=/hf_cache，运行阶段同步暴露该环境变量
#
# 镜像定位：环境镜像（environment image）
#   - 只含 Python 依赖 + 预下载的模型权重
#   - 业务代码（backend/、rag/、docs/）通过 volume 挂载，不打包进镜像
#   - 更新代码无需重新 build 镜像

# ========== 第一阶段：构建阶段 ==========
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装编译工具和系统依赖
# libmupdf-dev: PyMuPDF / PDF 处理依赖
# gcc / g++: 部分 Python 包需要编译
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（含新增的 sentence-transformers）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载 BAAI/bge-m3 模型权重（~1.3 GB）
# HF_HOME 设为固定路径，方便从 builder 阶段复制到 runtime 阶段
# 如需使用国内镜像，在 build 时传入：--build-arg HF_ENDPOINT=https://hf-mirror.com
ARG HF_ENDPOINT=https://huggingface.co
ENV HF_HOME=/hf_cache
ENV HUGGINGFACE_HUB_TOKEN=""
RUN python -c "\
import os; \
os.environ['HF_ENDPOINT'] = '${HF_ENDPOINT}'; \
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('BAAI/bge-m3'); \
print('BGE-M3 download complete')"

# ========== 第二阶段：运行阶段 ==========
FROM python:3.11-slim

WORKDIR /app

# 从构建阶段复制 Python 依赖
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 从构建阶段复制预下载的 BGE-M3 模型权重
COPY --from=builder /hf_cache /hf_cache

# 加入 requirements.txt 便于后续比对版本
COPY requirements.txt /app/requirements.txt

# 创建必要目录（数据、PDF、结果）
RUN mkdir -p /app/data /app/v0_1PDF /app/v0_1results

# 设置默认环境变量
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/hf_cache
ENV BIZ_DB_PATH=/app/data/hap_v01.db
ENV TRACE_DB_PATH=/app/data/hap_trace.db

# 默认命令（进入 Python 交互模式；实际使用通过 docker run 覆盖）
CMD ["python"]
