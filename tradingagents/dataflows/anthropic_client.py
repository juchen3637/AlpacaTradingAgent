"""Shared Anthropic client for thread-safe concurrent API calls."""
from anthropic import Anthropic
import threading
from typing import Optional
from .config import get_api_key

_client: Optional[Anthropic] = None
_lock = threading.Lock()


def get_anthropic_client(timeout: float = 300.0) -> Anthropic:
    """
    Get or create the shared Anthropic client instance.

    Thread-safe singleton pattern ensures all threads share the same
    HTTP connection pool for optimal parallel performance.

    Args:
        timeout: Request timeout in seconds (default: 300.0)

    Returns:
        Shared Anthropic client instance
    """
    global _client

    if _client is None:
        with _lock:
            if _client is None:
                api_key = get_api_key("anthropic_api_key", "ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("Anthropic API key not found. Please set ANTHROPIC_API_KEY environment variable.")

                _client = Anthropic(
                    api_key=api_key,
                    timeout=timeout,
                    max_retries=3
                )

    return _client
