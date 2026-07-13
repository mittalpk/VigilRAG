import httpx
from typing import Optional

class HTTPClient:
    client: Optional[httpx.AsyncClient] = None

    @classmethod
    async def start(cls):
        if cls.client is None:
            cls.client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0, read=60.0),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10)
            )

    @classmethod
    async def stop(cls):
        if cls.client is not None:
            await cls.client.aclose()
            cls.client = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls.client is None:
            cls.client = httpx.AsyncClient()
        return cls.client

# Global instance for easy access
http_client = HTTPClient()
