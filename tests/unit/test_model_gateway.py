from canada_funeral_intel.model_gateway import (
    NVCF_PROXY_DEFAULT,
    nvidia_chat_config,
)
from canada_funeral_intel.people.agent_review import _response_text


def test_nvidia_config_uses_local_proxy_and_translates_full_model(monkeypatch):
    monkeypatch.delenv("NVCF_PROXY_URL", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "proxy-owned-key")

    endpoint, model, api_key = nvidia_chat_config(
        "deepseek-ai/deepseek-v4-flash-0731"
    )

    assert endpoint == NVCF_PROXY_DEFAULT
    assert model == "deepseek-v4-flash"
    assert api_key == "proxy-owned-key"


def test_nvidia_config_allows_custom_proxy_and_alias(monkeypatch):
    monkeypatch.setenv("NVCF_PROXY_URL", "http://proxy.example/v1/chat/completions")

    endpoint, model, _ = nvidia_chat_config("llama-3.1-70b")

    assert endpoint == "http://proxy.example/v1/chat/completions"
    assert model == "llama-3.1-70b"


def test_response_text_accepts_openai_content_parts_and_nested_response():
    assert _response_text(
        {"choices": [{"message": {"content": [{"type": "text", "text": "OK"}]}}]}
    ) == "OK"
    assert _response_text(
        {"response": {"choices": [{"message": {"content": "OK"}}]}}
    ) == "OK"
    assert _response_text(
        {"choices": [{"message": {"reasoning_content": "OK"}}]}
    ) == "OK"
