"""Download the worker's model weights at image build time, so a cold start never downloads them.

    HF_HOME=/models python workers/gpu/fetch_weights.py

Runs inside the Dockerfile before the app code is copied, so it names the models itself;
backend/tests/test_worker_image.py checks the list matches workers/gpu/app.py.
"""

from __future__ import annotations

from huggingface_hub import snapshot_download

MODELS = {
    "lighting": "prs-eth/marigold-iid-lighting-v1-1",
}


def main() -> None:
    for name, repo in MODELS.items():
        path = snapshot_download(repo)
        print(f"{name}: {repo} -> {path}")


if __name__ == "__main__":
    main()
