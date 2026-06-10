# Docker Usage

Docker is used as an **environment image**. The image contains Python
dependencies and the preloaded BGE-M3 model cache, while the repository source
code is mounted into `/app` at runtime.

There are two supported image workflows:

1. Build the environment image locally from this repository.
2. Pull a prebuilt image from Docker Hub.

## Local Build

The recommended local demo image tag is `bioforge:demo`.

```bash
cd D:\Dev\BioForge\demo
cp .env.example .env
```

Fill `.env` with real values for LLM, RAGFlow, and NCBI credentials. The Docker
build-related defaults should be:

```env
DOCKER_IMAGE=bioforge
DOCKER_TAG=demo
HF_ENDPOINT=https://huggingface.co
PYTORCH_VERSION=2.12.0
```

Build with Docker Compose:

```bash
docker compose build bioforge
```

Equivalent direct Docker build:

```bash
docker build \
  --build-arg HF_ENDPOINT=https://huggingface.co \
  --build-arg PYTORCH_VERSION=2.12.0 \
  -t bioforge:demo .
```

If HuggingFace access is slow, use a mirror:

```bash
docker build \
  --build-arg HF_ENDPOINT=https://hf-mirror.com \
  --build-arg PYTORCH_VERSION=2.12.0 \
  -t bioforge:demo .
```

Run an environment check:

```bash
docker compose run --rm bioforge python -m backend.src.cli --check-only
```

Start the interactive CLI:

```bash
docker compose run --rm bioforge python -m backend.src.cli
```

Equivalent manual `docker run`:

```bash
docker run -it --rm \
  --name bioforge-demo-test \
  -v "D:\Dev\BioForge\demo:/app" \
  --env-file "D:\Dev\BioForge\demo\.env" \
  -w /app \
  bioforge:demo \
  python -m backend.src.cli
```

## Docker Hub Image

For users who do not want to build BGE-M3 locally, a prebuilt Docker Hub image
can be used.

Recommended tag policy:

- `jamesizhao/bioforge:demo`: moving demo tag for the latest tested demo image.
- `jamesizhao/bioforge:0.1.x`: immutable version tags for reproducible demos.

Using `:demo` on Docker Hub is valid and convenient, but it should be treated as
a moving alias. For papers, releases, or long-running demos, prefer a pinned
version tag such as `:0.1.4`.

To use the moving demo tag:

```env
DOCKER_IMAGE=jamesizhao/bioforge
DOCKER_TAG=demo
```

Pull and run:

```bash
docker compose pull bioforge
docker compose run --rm bioforge python -m backend.src.cli --check-only
docker compose run --rm bioforge python -m backend.src.cli
```

To use a pinned version:

```env
DOCKER_IMAGE=jamesizhao/bioforge
DOCKER_TAG=0.1.4
```

Then run the same Compose commands.

## BGE-M3 Notes

The Dockerfile preloads `BAAI/bge-m3` during image build with the same runtime
loader used by the RAG code:

```bash
python -c "from FlagEmbedding import BGEM3FlagModel; BGEM3FlagModel('BAAI/bge-m3', use_fp16=False)"
```

The model cache is stored at `/hf_cache` inside the image. Do not mount an empty
host directory over `/hf_cache` unless you intentionally want to manage the
cache yourself.

The validated local build produced a runtime image that successfully:

- Imported `paperscraper.pdf`, `pymed_paperscraper`, `eutils`, `rank_bm25`,
  `FlagEmbedding`, `chromadb`, `torch`, and related packages.
- Loaded `BAAI/bge-m3` from `/hf_cache`.
- Ran `docker compose config --quiet` successfully.
