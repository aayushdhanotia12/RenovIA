"""Image-editing models for the render bake-off, each behind one call: edit(images, prompt) -> JPEG/PNG bytes.

A provider is used only when its key is in the environment. Model ids are arguments, so a
newer version is a one-word change in render-eval.yml. Nothing here prices anything.
"""

from __future__ import annotations

import base64
import os
import time

try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

TIMEOUT = httpx.Timeout(300.0, connect=30.0)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _mime(data: bytes) -> str:
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


class Provider:
    key_env = ""
    name = ""

    def __init__(self, model: str) -> None:
        self.model = model
        self.key = os.environ.get(self.key_env, "")

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"

    def available(self) -> bool:
        return bool(self.key)

    def edit(self, images: list[bytes], prompt: str) -> bytes:  # pragma: no cover - network
        raise NotImplementedError


class OpenAIImages(Provider):
    """OpenAI's image edits endpoint (GPT Image models). Several input images are allowed;
    `input_fidelity=high` asks the model to keep the input's details where it supports it."""
    key_env, name = "OPENAI_API_KEY", "openai"

    def __init__(self, model: str, quality: str = "high") -> None:
        super().__init__(model)
        self.quality = quality

    def edit(self, images, prompt):
        files = [("image[]", (f"in{i}.{'png' if _mime(d) == 'image/png' else 'jpg'}", d, _mime(d)))
                 for i, d in enumerate(images)]
        data = {"model": self.model, "prompt": prompt, "n": "1", "size": "auto", "quality": self.quality,
                "input_fidelity": "high"}
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post("https://api.openai.com/v1/images/edits", headers={"Authorization": f"Bearer {self.key}"},
                       data=data, files=files)
            if r.status_code == 400 and "input_fidelity" in r.text:  # a model without the setting
                data.pop("input_fidelity")
                r = c.post("https://api.openai.com/v1/images/edits", headers={"Authorization": f"Bearer {self.key}"},
                           data=data, files=files)
        r.raise_for_status()
        return base64.b64decode(r.json()["data"][0]["b64_json"])


class GeminiImages(Provider):
    """Google's Gemini image models (Nano Banana family) through generateContent."""
    key_env, name = "GEMINI_API_KEY", "google"

    def edit(self, images, prompt):
        parts = [{"text": prompt}] + [{"inline_data": {"mime_type": _mime(d), "data": _b64(d)}} for d in images]
        body = {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"]}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(url, headers={"x-goog-api-key": self.key}, json=body)
        r.raise_for_status()
        for part in r.json()["candidates"][0]["content"]["parts"]:
            blob = part.get("inlineData") or part.get("inline_data")
            if blob:
                return base64.b64decode(blob["data"])
        raise RuntimeError(f"no image in the answer: {str(r.json())[:300]}")


class FalImages(Provider):
    """Any edit model hosted on fal.ai (Seedream, FLUX, Qwen, Nano Banana, ...), through its queue.
    `image_field` is the model's input name: most take a list `image_urls`, some a single `image_url`."""
    key_env, name = "FAL_KEY", "fal"

    def __init__(self, model: str, image_field: str = "image_urls", extra: dict | None = None) -> None:
        super().__init__(model)
        self.image_field, self.extra = image_field, extra or {}

    def edit(self, images, prompt):
        uris = [f"data:{_mime(d)};base64,{_b64(d)}" for d in images]
        body = {"prompt": prompt, **self.extra}
        body[self.image_field] = uris if self.image_field.endswith("s") else uris[0]
        head = {"Authorization": f"Key {self.key}"}
        with httpx.Client(timeout=TIMEOUT) as c:
            sub = c.post(f"https://queue.fal.run/{self.model}", headers=head, json=body)
            sub.raise_for_status()
            job = sub.json()
            for _ in range(240):
                st = c.get(job["status_url"], headers=head).json()
                if st.get("status") == "COMPLETED":
                    break
                time.sleep(2)
            res = c.get(job["response_url"], headers=head)
            res.raise_for_status()
            out = res.json()
            url = (out.get("images") or [out.get("image")])[0]["url"]
            img = c.get(url)
            img.raise_for_status()
            return img.content


class XAIImages(Provider):
    """xAI's Grok image models through the OpenAI-style images endpoint."""
    key_env, name = "XAI_API_KEY", "xai"

    def edit(self, images, prompt):
        body = {"model": self.model, "prompt": prompt, "response_format": "b64_json",
                "image": [{"url": f"data:{_mime(d)};base64,{_b64(d)}", "type": "image_url"} for d in images]}
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post("https://api.x.ai/v1/images/edits", headers={"Authorization": f"Bearer {self.key}"}, json=body)
        r.raise_for_status()
        return base64.b64decode(r.json()["data"][0]["b64_json"])
