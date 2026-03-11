"""
LLM client factory for OpenAI and OpenAI-compatible internal APIs
(e.g. Centralized Inference Service / CIS).

Per CIS docs: the OpenAI-compatible endpoint is
  POST {base_url}/chat/completions  with base_url = .../v1alpha1/openai/v1
So set LLM_BASE_URL=https://.../v1alpha1/openai/v1 and use the standard client.
Model must be provider/model (e.g. aviato-turbo/aviato-turbo).
Auth: Wd-PCA-Feature-Key header; LLM_VERIFY_SSL=false on dev.
Optional LLM_CHAT_PATH: use a custom path instead of .../openai/v1/chat/completions.
"""

import urllib.parse
from typing import Any, List, Mapping

import httpx
from openai import OpenAI


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("Message", (), {"content": content})()


class _InternalCISClient:
    """Direct POST to CIS (same as test_llm_connection.py). Avoids OpenAI client connection issues."""

    def __init__(self, config):
        self._config = config
        self._base = config.llm_base_url.rstrip("/")
        # Default "chat/completions" so URL is .../openai/v1/chat/completions when base is .../openai/v1
        self._path = (config.llm_chat_path or "chat/completions").strip()
        self._url = f"{self._base}/{self._path}"
        self._headers = {config.llm_auth_header: config.llm_api_key, "Content-Type": "application/json"}
        self._params = {}
        if config.llm_extra_query:
            for part in config.llm_extra_query.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    self._params[k.strip()] = v.strip()
        self._verify = config.llm_verify_ssl

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, *, model: str, messages: List[Mapping[str, Any]], temperature: float = 0, **kwargs) -> Any:
        body = {"model": model, "messages": list(messages), "temperature": temperature, **kwargs}
        timeout = getattr(self._config, "llm_timeout", 300.0)
        with httpx.Client(verify=self._verify, timeout=timeout) as client:
            r = client.post(self._url, json=body, headers=self._headers, params=self._params or None)
        r.raise_for_status()
        data = r.json()
        content = ""
        if isinstance(data, dict) and "choices" in data and len(data["choices"]) > 0:
            content = (data["choices"][0].get("message") or {}).get("content") or ""
        return type("Response", (), {"choices": [_FakeChoice(content)]})()


def _make_http_client(config):
    """Build httpx client for internal CIS: verify=False and optional extra query params."""
    verify = config.llm_verify_ssl
    extra_query = (config.llm_extra_query or "").strip()

    def add_extra_query(request):
        if not extra_query:
            return
        parsed = urllib.parse.urlparse(request.url)
        qs = urllib.parse.parse_qs(parsed.query)
        for part in extra_query.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                qs[k.strip()] = [v.strip()]
        new_query = urllib.parse.urlencode(qs, doseq=True)
        request.url = request.url.copy_with(query=new_query)

    event_hooks = {"request": [add_extra_query]} if extra_query else {}
    # Always use a custom client for internal so verify=False is applied (avoids APIConnectionError)
    return httpx.Client(verify=verify, event_hooks=event_hooks)


def get_llm_client(config):
    """
    Return an OpenAI client configured for the chosen provider.

    - openai: uses OPENAI_API_KEY and default OpenAI base URL.
    - internal: uses LLM_BASE_URL, LLM_API_KEY as Wd-PCA-Feature-Key (or
      LLM_AUTH_HEADER), and optional LLM_VERIFY_SSL=false.
    """
    if config.llm_provider == "openai":
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return OpenAI(api_key=config.openai_api_key)

    if config.llm_provider == "internal":
        if not config.llm_base_url:
            raise ValueError("LLM_BASE_URL is required when LLM_PROVIDER=internal")
        if not config.llm_api_key:
            raise ValueError("LLM_API_KEY is required when LLM_PROVIDER=internal")
        # Always use direct POST (same as test_llm_connection.py); OpenAI client was still failing.
        return _InternalCISClient(config)

    raise ValueError(
        f"Unsupported LLM_PROVIDER: {config.llm_provider}. "
        "Use 'openai' or 'internal'."
    )
