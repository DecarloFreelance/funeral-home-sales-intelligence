"""Provider endpoint and model-name configuration for agent model calls."""

from __future__ import annotations

import os

NVCF_PROXY_DEFAULT = "http://127.0.0.1:8000/v1/chat/completions"

# The proxy exposes stable aliases while the application historically accepted
# NVIDIA's full model IDs. Keep this mapping in one place so every agent stage
# sends the name the proxy expects.
NVCF_MODEL_ALIASES = {
    "meta/llama-3.1-8b-instruct": "llama-3.1-8b",
    "meta/llama-3.1-70b-instruct": "llama-3.1-70b",
    "nvidia/nemotron-3-super-120b-a12b": "nemotron-super-120b",
    "nvidia/nemotron-3-ultra-550b-a55b": "nemotron-ultra-550b",
    "deepseek-ai/deepseek-v4-flash-0731": "deepseek-v4-flash",
}


def nvidia_chat_config(model: str) -> tuple[str, str, str]:
    """Return ``(endpoint, proxy_model, api_key)`` for NVIDIA chat calls.

    The proxy owns the NVIDIA credential, so the client-side key is optional.
    ``NVCF_PROXY_URL`` may point at another compatible proxy instance.
    """

    endpoint = os.environ.get("NVCF_PROXY_URL", NVCF_PROXY_DEFAULT).strip()
    if not endpoint:
        endpoint = NVCF_PROXY_DEFAULT
    return endpoint, NVCF_MODEL_ALIASES.get(model, model), os.environ.get(
        "NVIDIA_API_KEY", ""
    ).strip()
