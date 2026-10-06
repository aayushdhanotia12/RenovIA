"""Alternative deploy of the model worker on Modal (the main one is Cloud Run: README, "Deploying the model worker").

    pip install modal && modal setup                     # once, with the team's Modal account
    modal secret create renovai-worker RENOVAI_WORKER_TOKEN=<a long random string>
    modal deploy workers/gpu/modal_app.py

Modal prints the worker's URL; set RENOVAI_WORKER_URL to it and RENOVAI_WORKER_TOKEN to the
same token on the app server. Untested until the account exists: check it with
`curl -H "Authorization: Bearer $TOKEN" $URL/health` after the first deploy.
"""

import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch", "diffusers>=0.33", "transformers>=4.44", "accelerate", "starlette>=0.37", "numpy",
                 "pillow")
    .add_local_python_source("workers")
)
app = modal.App("renovai-models")


@app.function(gpu="L4", image=image, scaledown_window=300, timeout=600,
              secrets=[modal.Secret.from_name("renovai-worker")])
@modal.concurrent(max_inputs=4)
@modal.asgi_app()
def web():
    from workers.gpu.app import create_app
    return create_app()
