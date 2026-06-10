# BioForge Docker Environment

This project treats Docker as an environment image, not as an application bundle.
The image provides Python dependencies and local model weights. The repository
source code is mounted into `/app` at runtime.

## Runtime Responsibilities

The image should contain:

- Python 3.11 runtime.
- BioForge Python dependencies from `requirements.txt`.
- PDF/search/download dependencies used by `download_paper` and `screen_paper`.
- RAG dependencies used by `rag/`, including `FlagEmbedding`, BGE-M3, and optional `chromadb`.
- A preloaded `BAAI/bge-m3` HuggingFace cache under `/hf_cache`.

The image should not contain:

- `.env` secrets.
- Project run artifacts.
- Business data created during a run.

Those are mounted at runtime.

## Important Runtime Paths

- `/app`: mounted project workspace.
- `/app/data`: mounted run data, PDFs, trace files, SQLite databases, and CSV output.
- `/hf_cache`: baked HuggingFace model cache copied from the Docker builder stage.

Do not mount an empty volume over `/hf_cache` by default. It would hide the
preloaded BGE-M3 weights baked into the image. If a persistent external HF cache
is needed, prime the volume first or allow the first run to download the model.

## Required Environment Variables

Core paths:

- `DATA_ROOT=/app/data`
- `EXTRACTION_PROFILE=hap_peptide_v1`
- `BIZ_DB_PATH=/app/data/hap_v01.db`
- `TRACE_DB_PATH=/app/data/hap_trace.db`

HuggingFace and BGE:

- `HF_HOME=/hf_cache`
- `HUGGINGFACE_HUB_CACHE=/hf_cache/hub`
- `TRANSFORMERS_CACHE=/hf_cache/hub`
- `BGE_MODEL_DIR=BAAI/bge-m3`
- `BGE_USE_FP16=false`

RAGFlow and RAG:

- `RAGFLOW_API_BASE_URL=https://ragflow.adlumen.top`
- `RAGFLOW_API_KEY=<secret>`
- `RAGFLOW_CHUNK_METHOD=paper` or `naive`
- `RAGFLOW_POLL_TIMEOUT_SEC=600`
- `RAG_USE_CHROMADB=false`
- `RAG_MAX_ENTITIES_PER_PAPER=3`

LLM:

- `LLM_API_KEY=<secret>`
- `LLM_BASE_URL=<OpenAI-compatible base URL>`
- `LLM_MODEL=<model>`
- `LLM_TIMEOUT_SEC=120`

NCBI/download:

- `NCBI_EMAIL=<email>`
- `NCBI_API_KEY=<optional key>`

## What Was Found In The Existing Test Container

The long-lived `bioforge-dev` container had manually installed packages and
manually populated model cache. It was useful for debugging, but it was not a
reproducible image state.

Observed model cache:

- `/hf_cache` existed and was about 4.3 GB.
- `BAAI/bge-m3` snapshot had `pytorch_model.bin` present.
- The process environment did not expose `HF_HOME`, `BGE_MODEL_DIR`, or related
  variables, which means a fresh `docker run --rm` would not necessarily behave
  the same way unless the image or `.env` sets them.

Observed missing imports before the Dockerfile/requirements cleanup:

- `pymed_paperscraper` was missing, so `paperscraper.pdf.save_pdf` could not be
  imported correctly.
- `eutils` was missing.
- `rank_bm25` was missing.

Observed extra transitive packages:

- `FlagEmbedding` installed `torch`, `transformers`, `sentence-transformers`,
  `accelerate`, `datasets`, `peft`, `sentencepiece`, and related libraries.
- Default PyPI resolution pulled a CUDA-enabled Torch stack with many
  `nvidia-*` packages. The Dockerfile now installs CPU Torch first to avoid that
  for the demo environment.
- `chromadb` installed `onnxruntime`, OpenTelemetry packages, `kubernetes`,
  `uvicorn`, and related dependencies. The runtime default is
  `RAG_USE_CHROMADB=false`, so the in-memory adapter is used unless explicitly
  enabled.

## Build

From the repository root:

```bash
docker compose build bioforge
```

Or directly:

```bash
docker build \
  --build-arg HF_ENDPOINT=https://huggingface.co \
  --build-arg PYTORCH_VERSION=2.12.0 \
  -t bioforge:local .
```

For a HuggingFace mirror:

```bash
docker build \
  --build-arg HF_ENDPOINT=https://hf-mirror.com \
  --build-arg PYTORCH_VERSION=2.12.0 \
  -t bioforge:local .
```

## Run

Using Compose:

```bash
docker compose run --rm bioforge python -m backend.src.cli
```

Manual `docker run`:

```bash
docker run -it --rm \
  -v "D:\Dev\BioForge\template_agent_dev:/app" \
  --env-file "D:\Dev\BioForge\template_agent_dev\.env" \
  -w /app \
  bioforge:local \
  python -m backend.src.cli
```

## Smoke Checks

Dependency import check:

```bash
python - <<'PY'
import importlib
for name in [
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
]:
    importlib.import_module(name)
print("imports ok")
PY
```

BGE load check:

```bash
python - <<'PY'
from FlagEmbedding import BGEM3FlagModel
BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
print("bge ok")
PY
```

CLI environment check:

```bash
python -m backend.src.cli --check-only
```
