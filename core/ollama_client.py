"""Ollama API client with retry logic and structured JSON output."""

import json
import httpx
import logging
from typing import Any, Optional
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import yaml
import os

logger = logging.getLogger(__name__)


def _load_ollama_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'system.yaml')
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg['ollama']


class OllamaError(Exception):
    """Raised when Ollama API call fails after retries."""
    pass


class OllamaClient:
    """
    Wrapper for Ollama HTTP API.

    Features:
    - Automatic retry with exponential backoff (tenacity)
    - Configurable timeout per call
    - Structured JSON output mode (format="json")
    - Separate methods for analysis vs code generation
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        retry_attempts: Optional[int] = None,
        retry_backoff_factor: Optional[float] = None,
    ) -> None:
        cfg = _load_ollama_config()
        self.base_url = (base_url or cfg['base_url']).rstrip('/')
        self.timeout_seconds = timeout_seconds or cfg['timeout_seconds']
        self.retry_attempts = retry_attempts or cfg['retry_attempts']
        self.retry_backoff_factor = retry_backoff_factor or cfg['retry_backoff_factor']
        self.analysis_model: str = cfg['analysis_model']    # llama3.2:3b
        self.code_gen_model: str = cfg['code_gen_model']    # qwen2.5-coder:7b

    # ------------------------------------------------------------------
    # Low-level HTTP call
    # ------------------------------------------------------------------

    def _call_generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        format_json: bool = False,
        temperature: float = 0.3,
    ) -> str:
        """Blocking HTTP call to Ollama /api/generate endpoint."""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format_json:
            payload["format"] = "json"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                response = data.get("response", "")
                # qwen3 thinking models put JSON in "thinking" when format=json is set
                # and response is empty — extract from thinking field as fallback
                if not response.strip() and format_json and data.get("thinking"):
                    thinking = data["thinking"]
                    import re as _re
                    m = _re.search(r"(\{.*\})", thinking, _re.DOTALL)
                    if m:
                        response = m.group(1)
                return response
        except httpx.TimeoutException as e:
            raise OllamaError(f"Ollama timeout after {self.timeout_seconds}s: {e}") from e
        except httpx.HTTPStatusError as e:
            raise OllamaError(f"Ollama HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.ConnectError as e:
            raise OllamaError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Is 'ollama serve' running?"
            ) from e

    # ------------------------------------------------------------------
    # Retry-wrapped call
    # ------------------------------------------------------------------

    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        format_json: bool = False,
        temperature: float = 0.3,
    ) -> str:
        """Generate text with automatic retry on failure."""
        @retry(
            stop=stop_after_attempt(self.retry_attempts),
            wait=wait_exponential(
                multiplier=self.retry_backoff_factor,
                min=1,
                max=30,
            ),
            retry=retry_if_exception_type(OllamaError),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _with_retry() -> str:
            return self._call_generate(model, prompt, system, format_json, temperature)

        return _with_retry()

    # ------------------------------------------------------------------
    # Typed helpers
    # ------------------------------------------------------------------

    def generate_json(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
    ) -> dict:
        """
        Generate and parse JSON response.
        Raises OllamaError if parsing fails after retries.
        """
        # Append /no_think to disable thinking mode on qwen3.x models
        # (thinking models put output in "thinking" field when format=json, leaving response empty)
        prompt_no_think = prompt + "\n/no_think"
        raw = self.generate(model=model, prompt=prompt_no_think, system=system, format_json=True)
        import re
        # Strip <think>...</think> blocks (qwen3.5 thinking mode)
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try JSON inside markdown fences
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            # Try first { ... } block in the cleaned text
            match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            raise OllamaError(
                f"Ollama returned non-JSON response: {raw[:200]}..."
            )

    def analyze(self, prompt: str, system: Optional[str] = None) -> dict:
        """Call llama3.2:3b for analysis tasks. Returns JSON dict."""
        return self.generate_json(
            model=self.analysis_model,
            prompt=prompt,
            system=system,
        )

    def generate_code(self, prompt: str, system: Optional[str] = None) -> str:
        """Call qwen2.5-coder:7b for code generation. Returns raw string."""
        return self.generate(
            model=self.code_gen_model,
            prompt=prompt,
            system=system,
            format_json=False,
            temperature=0.1,  # Low temperature for deterministic code
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """
        Check Ollama is running and required models are available.
        Returns {"ok": bool, "models": list, "missing": list}
        """
        required = {self.analysis_model, self.code_gen_model}
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                available = {m["name"] for m in data.get("models", [])}
                missing = [m for m in required if not any(
                    avail.startswith(m.split(":")[0]) for avail in available
                )]
                return {
                    "ok": len(missing) == 0,
                    "models": sorted(available),
                    "missing": missing,
                }
        except Exception as e:
            return {"ok": False, "models": [], "missing": list(required), "error": str(e)}
