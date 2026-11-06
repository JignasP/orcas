"""
LLM Gateway client for ORCAS worker agents.

On any gateway error (non-200, timeout, connection refused) this client raises
``LLMUnavailable`` instead of falling back to a local heuristic.  The pipeline
in ``tasks.py`` catches that exception and escalates the run with
``degraded=True``, which is the behaviour required by ARCHITECTURE §4.3.

There is *no* local heuristic path.  For offline testing use
``services.worker.clients.fake_llm.FakeLLMClient``.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("worker.llm_client")


class LLMUnavailable(Exception):
    """
    Raised when the LLM gateway cannot be reached or returns a non-200 response.

    Attributes
    ----------
    agent : str | None
        The agent that was calling the gateway (e.g. "researcher", "verifier").
    step : str | None
        The step name within the agent (e.g. "classify", "draft").
    """

    def __init__(self, message: str, agent: Optional[str] = None, step: Optional[str] = None):
        super().__init__(message)
        self.agent = agent
        self.step = step


class LLMClient:
    """Client for calling the ORCAS LLM Gateway from worker agents."""

    def __init__(self, gateway_url: Optional[str] = None):
        self.gateway_url = gateway_url or os.getenv(
            "LLM_GATEWAY_URL", "http://localhost:8002"
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        run_id: Optional[str] = None,
        agent: Optional[str] = None,
        step: Optional[str] = None,
        prompt_version: Optional[str] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Send a chat request to the LLM gateway.

        Raises
        ------
        LLMUnavailable
            If the gateway is unreachable, returns non-200, or times out.
        """
        payload = {
            "messages": messages,
            "temperature": temperature,
            "run_id": run_id,
            "agent": agent,
            "step": step,
            "prompt_version": prompt_version,
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{self.gateway_url}/v1/chat", json=payload)
                if resp.status_code == 200:
                    return resp.json()
                raise LLMUnavailable(
                    f"LLM Gateway returned HTTP {resp.status_code} for step={step}",
                    agent=agent,
                    step=step,
                )
        except LLMUnavailable:
            raise
        except Exception as exc:
            logger.warning(
                "LLM Gateway unreachable for agent=%s step=%s: %s",
                agent,
                step,
                exc,
                exc_info=True,
            )
            raise LLMUnavailable(
                f"LLM Gateway unreachable: {exc}",
                agent=agent,
                step=step,
            ) from exc

    @staticmethod
    def extract_json(text: str) -> Dict[str, Any]:
        """Extract the first JSON object from an LLM response string."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {}
