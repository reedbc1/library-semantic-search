"""Deterministic fakes for external HTTP and OpenAI clients."""

from collections import deque
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


@dataclass(frozen=True)
class HttpCall:
    method: str
    url: str
    kwargs: dict[str, Any]


class FakeResponse:
    def __init__(self, payload: Any, error: Exception | None = None):
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> Any:
        return self._payload


class FakeAsyncClientFactory:
    """Callable replacement for httpx.AsyncClient with queued responses."""

    def __init__(self, *responses: FakeResponse):
        self.responses = deque(responses)
        self.calls: list[HttpCall] = []
        self.constructor_kwargs: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> "FakeAsyncClient":
        self.constructor_kwargs.append(kwargs)
        return FakeAsyncClient(self)

    def next_response(self) -> FakeResponse:
        if not self.responses:
            raise AssertionError("No fake HTTP response remains")
        return self.responses.popleft()


class FakeAsyncClient:
    def __init__(self, factory: FakeAsyncClientFactory):
        self.factory = factory

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.factory.calls.append(HttpCall("GET", url, kwargs))
        return self.factory.next_response()

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.factory.calls.append(HttpCall("POST", url, kwargs))
        return self.factory.next_response()


class FakeSyncEmbeddings:
    def __init__(self, embedding: list[float]):
        self.embedding = embedding
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=list(self.embedding))]
        )


class FakeSyncOpenAIClient:
    def __init__(self, embedding: list[float]):
        self.embeddings = FakeSyncEmbeddings(embedding)


class FakeAsyncEmbeddings:
    def __init__(self, embedding: list[float]):
        self.embedding = embedding
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=list(self.embedding))]
        )


class FakeAsyncOpenAIClient:
    def __init__(self, embedding: list[float]):
        self.embeddings = FakeAsyncEmbeddings(embedding)
