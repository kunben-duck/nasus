import asyncio
import json

import httpx

from ...application.system_image.index_ports import IndexEmbeddingReply, IndexEmbeddingFailure
from ...domain.system_image.retrieval_index import BATCH_SIZE, CHUNK_BYTES, validate_vectors


class HTTPIndexEmbedding:
    """Bounded native embedding only: no mock, redirects, environment proxies or retries."""

    def __init__(self, *, transport=None):
        self.transport = transport

    async def embed(self, texts, model):
        try:
            return await asyncio.wait_for(self._request(texts, model), timeout=60)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise IndexEmbeddingFailure("index embedding failed; partial generations are not published") from None

    async def _request(self, texts, model):
        if (not 1 <= len(texts) <= BATCH_SIZE or any(not text or len(text.encode()) > CHUNK_BYTES for text in texts)
                or model.binding.provider not in {"openai", "openai_compatible"}):
            raise ValueError("invalid native embedding input")
        wire = json.dumps({"model": model.binding.model_name, "input": texts, "encoding_format": "float"}).encode()
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False, transport=self.transport) as client:
            async with client.stream("POST", model.binding.base_url + "/embeddings",
                    headers={"Authorization": "Bearer " + model.api_key, "Content-Type": "application/json"}, content=wire) as response:
                response.raise_for_status()
                parts, size = [], 0
                async for part in response.aiter_bytes():
                    size += len(part)
                    if size > 8 * 1024 * 1024:
                        raise ValueError("embedding response exceeds budget")
                    parts.append(part)
        body = json.loads(b"".join(parts))
        rows = body["data"]
        if (not isinstance(rows, list) or len(rows) != len(texts)
                or any(type(row.get("index")) is not int for row in rows)
                or sorted(row["index"] for row in rows) != list(range(len(texts)))):
            raise ValueError("embedding result indices are incomplete or duplicated")
        if body.get("model") not in {None, model.binding.model_name}:
            raise ValueError("embedding model mismatch")
        vectors = validate_vectors([row["embedding"] for row in sorted(rows, key=lambda row: row["index"])], len(texts))
        tokens = body.get("usage", {}).get("prompt_tokens")
        valid = type(tokens) is int and tokens >= 0
        return IndexEmbeddingReply(vectors, tokens if valid else 0, "provider" if valid else "none")
