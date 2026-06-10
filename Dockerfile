# BioForge environment image.
#
# This image is used as an environment manager: project source code is mounted
# at /app during development, while Python dependencies and BGE-M3 weights are
# baked into the image for reproducible CLI/RAG runs.

FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

ARG HF_ENDPOINT=https://huggingface.co
ARG PYTORCH_VERSION=2.12.0

ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/hf_cache
ENV HUGGINGFACE_HUB_CACHE=/hf_cache/hub
ENV TRANSFORMERS_CACHE=/hf_cache/hub
ENV HF_ENDPOINT=${HF_ENDPOINT}
ENV BGE_MODEL_DIR=BAAI/bge-m3
ENV BGE_USE_FP16=false

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU PyTorch first. Without this, pip may resolve the default CUDA
# wheel and pull many nvidia-* packages that are unnecessary for the demo CLI.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==${PYTORCH_VERSION}" \
    && pip install --no-cache-dir -r requirements.txt

# Fail the build early if the downloader/screen/RAG imports are incomplete.
RUN python - <<'PY'
import importlib

modules = [
    "Bio",
    "metapub",
    "paperscraper.pdf",
    "pymed_paperscraper",
    "eutils",
    "rank_bm25",
    "fitz",
    "FlagEmbedding",
    "chromadb",
    "torch",
    "transformers",
    "sentence_transformers",
]
for name in modules:
    importlib.import_module(name)
print("BioForge dependency import smoke test passed")
PY

# Preload BGE-M3 with the same runtime loader used by rag/retrieval.
RUN python - <<'PY'
from FlagEmbedding import BGEM3FlagModel

BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
print("BGE-M3 FlagEmbedding load check complete")
PY


FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/hf_cache
ENV HUGGINGFACE_HUB_CACHE=/hf_cache/hub
ENV TRANSFORMERS_CACHE=/hf_cache/hub
ENV BGE_MODEL_DIR=BAAI/bge-m3
ENV BGE_USE_FP16=false
ENV RAG_USE_CHROMADB=false
ENV RAGFLOW_CHUNK_METHOD=paper
ENV RAGFLOW_POLL_TIMEOUT_SEC=600
ENV RAG_MAX_ENTITIES_PER_PAPER=3
ENV LLM_TIMEOUT_SEC=120
ENV DATA_ROOT=/app/data
ENV EXTRACTION_PROFILE=hap_peptide_v1
ENV BIZ_DB_PATH=/app/data/hap_v01.db
ENV TRACE_DB_PATH=/app/data/hap_trace.db

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /hf_cache /hf_cache
COPY requirements.txt /app/requirements.txt

RUN mkdir -p /app/data /app/v0_1PDF /app/v0_1results

CMD ["python"]
