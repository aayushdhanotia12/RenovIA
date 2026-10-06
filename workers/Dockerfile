# The model worker image, for an NVIDIA GPU (Cloud Run with an L4, or any CUDA host).
#
#   docker build -t renovai-models workers
#   docker run --gpus all -e RENOVAI_WORKER_TOKEN=... -p 8080:8080 renovai-models
#
# Built and deployed by .github/workflows/deploy-worker.yml. The weights are baked into the
# image (about the size of the CUDA libraries again), so a cold start loads them from local
# disk instead of downloading them.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models
WORKDIR /app

# PyTorch's Linux wheels on PyPI carry their own CUDA libraries; Cloud Run provides the driver.
RUN pip install "torch>=2.5"
COPY gpu/requirements.txt /app/workers/gpu/requirements.txt
RUN pip install -r /app/workers/gpu/requirements.txt

COPY gpu/fetch_weights.py /app/fetch_weights.py
RUN python /app/fetch_weights.py

COPY __init__.py /app/workers/__init__.py
COPY gpu/ /app/workers/gpu/
# Everything the worker needs is in the image now; never reach Hugging Face at run time.
ENV HF_HUB_OFFLINE=1

CMD exec uvicorn --factory workers.gpu.app:create_app --host 0.0.0.0 --port "${PORT:-8080}"
