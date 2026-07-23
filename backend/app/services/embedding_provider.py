"""
Embedding Provider Module (US-006, US-007, US-008).

Provides unified embedding generation with:
- GeminiEmbeddingProvider (uses Google text-embedding-004 API when GEMINI_API_KEY / GOOGLE_API_KEY is available)
- DeterministicEmbeddingProvider (reusable hash-seeded fallback for unit tests and offline mode)
"""

from abc import ABC, abstractmethod
import hashlib
import json
import logging
import os
from typing import List, Optional
import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSION = 768


class BaseEmbeddingProvider(ABC):
    """Abstract base class for text embedding generation."""

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Generates a 768-dimensional float embedding vector for a single text string."""
        pass

    @abstractmethod
    async def embed_text_async(self, text: str) -> List[float]:
        """Async variant for text embedding generation."""
        pass


class DeterministicEmbeddingProvider(BaseEmbeddingProvider):
    """Hash-seeded deterministic fallback provider for testing / offline execution."""

    def __init__(self, dimension: int = EMBEDDING_DIMENSION):
        self.dimension = dimension

    def embed_text(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dimension
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)
        return [(float((seed + i * 31) % 100) / 100.0) for i in range(self.dimension)]

    async def embed_text_async(self, text: str) -> List[float]:
        return self.embed_text(text)


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini text-embedding-004 API provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "models/text-embedding-004",
        dimension: int = EMBEDDING_DIMENSION,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.model = model
        self.dimension = dimension
        self._fallback = DeterministicEmbeddingProvider(dimension=dimension)

    def embed_text(self, text: str) -> List[float]:
        if not self.api_key:
            logger.debug("GEMINI_API_KEY not set; using deterministic embedding provider fallback.")
            return self._fallback.embed_text(text)

        url = f"https://generativelanguage.googleapis.com/v1beta/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": self.model,
            "content": {"parts": [{"text": text}]},
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    values = data.get("embedding", {}).get("values", [])
                    if values and len(values) == self.dimension:
                        return [float(v) for v in values]
                logger.warning(f"Gemini embedding API returned HTTP {response.status_code}. Using fallback.")
        except Exception as exc:
            logger.warning(f"Gemini embedding request failed ({exc}). Using fallback.")

        return self._fallback.embed_text(text)

    async def embed_text_async(self, text: str) -> List[float]:
        if not self.api_key:
            return self._fallback.embed_text(text)

        url = f"https://generativelanguage.googleapis.com/v1beta/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": self.model,
            "content": {"parts": [{"text": text}]},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    values = data.get("embedding", {}).get("values", [])
                    if values and len(values) == self.dimension:
                        return [float(v) for v in values]
                logger.warning(f"Gemini async embedding API returned HTTP {response.status_code}. Using fallback.")
        except Exception as exc:
            logger.warning(f"Gemini async embedding request failed ({exc}). Using fallback.")

        return self._fallback.embed_text(text)


def get_embedding_provider() -> BaseEmbeddingProvider:
    """Factory returning appropriate EmbeddingProvider instance."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if api_key:
        return GeminiEmbeddingProvider(api_key=api_key)
    return DeterministicEmbeddingProvider()
