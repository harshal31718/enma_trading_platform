"""Plan 6 Step 6.1 (ENG-1) / Step 6.5 (ENG-16) unit tests for `NodeNotifier` —
extracted from `LiveBotManager` as a pure move (behavior-preserving — see
golden-master `before_plan6.json`/`after_plan6_1b.json`, byte-identical),
then given a lazy pooled `httpx.AsyncClient` singleton instead of a fresh
client per call (`after_plan6_5a.json`), then (2026-07-24) had `notify()`'s
transport switched from a fire-and-forget HTTP PATCH to a durable Redis
Stream `XADD` — see the module docstring and `0_fixes-queue.md`'s Plan 6.5
entry for the full design/safety argument. `call_internal()` is unchanged
(still HTTP, synchronous request/response).

Run inside the container::

    docker exec enma_trading_platform-engine-1 pytest /app/tests/test_node_notifier.py
"""
import asyncio
import json

import core.node_notifier as notifier_mod
from core.node_notifier import NodeNotifier


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, calls, response_payload=None, raise_exc=None):
        self._calls = calls
        self._response_payload = response_payload
        self._raise_exc = raise_exc

    async def patch(self, url, json=None, headers=None, timeout=None):
        if self._raise_exc:
            raise self._raise_exc
        self._calls.append(("PATCH", url, json, headers, timeout))

    async def post(self, url, json=None, headers=None, timeout=None):
        if self._raise_exc:
            raise self._raise_exc
        self._calls.append(("POST", url, json, headers, timeout))
        return _FakeResp(self._response_payload)


class _FakeRedis:
    def __init__(self, calls, raise_exc=None):
        self._calls = calls
        self._raise_exc = raise_exc

    async def xadd(self, name, fields, maxlen=None, approximate=True):
        if self._raise_exc:
            raise self._raise_exc
        self._calls.append((name, fields, maxlen, approximate))

    async def aclose(self):
        pass


def _reset_client_singleton(monkeypatch):
    monkeypatch.setattr(notifier_mod, "_client", None)


def _reset_redis_singleton(monkeypatch):
    monkeypatch.setattr(notifier_mod, "_redis_client", None)


def test_notify_publishes_to_the_stream_with_session_id_and_json_payload(monkeypatch):
    _reset_redis_singleton(monkeypatch)
    calls = []
    monkeypatch.setattr(notifier_mod, "_get_redis_client", lambda: _FakeRedis(calls))

    notifier = NodeNotifier()
    _run(notifier.notify("sess1", {"pnl": 1.0}))

    assert len(calls) == 1
    name, fields, maxlen, approximate = calls[0]
    assert name == notifier_mod.STREAM_KEY
    assert fields["sessionId"] == "sess1"
    assert json.loads(fields["payload"]) == {"pnl": 1.0}
    assert maxlen == notifier_mod.STREAM_MAXLEN
    assert approximate is True


def test_notify_swallows_exceptions(monkeypatch):
    _reset_redis_singleton(monkeypatch)
    monkeypatch.setattr(
        notifier_mod, "_get_redis_client",
        lambda: _FakeRedis([], raise_exc=RuntimeError("network down")),
    )
    notifier = NodeNotifier()
    # Must not raise — notification failures are best-effort/logged only,
    # same guarantee as the old PATCH transport.
    _run(notifier.notify("sess1", {"pnl": 1.0}))


def test_get_redis_client_returns_same_instance_across_calls(monkeypatch):
    _reset_redis_singleton(monkeypatch)
    c1 = notifier_mod._get_redis_client()
    c2 = notifier_mod._get_redis_client()
    assert c1 is c2
    _run(notifier_mod.close_redis_client())


def test_close_redis_client_clears_singleton_so_next_get_builds_fresh(monkeypatch):
    _reset_redis_singleton(monkeypatch)
    c1 = notifier_mod._get_redis_client()
    _run(notifier_mod.close_redis_client())
    assert notifier_mod._redis_client is None
    c2 = notifier_mod._get_redis_client()
    assert c1 is not c2
    _run(notifier_mod.close_redis_client())


def test_close_redis_client_is_a_noop_when_never_created(monkeypatch):
    _reset_redis_singleton(monkeypatch)
    # Must not raise even though _get_redis_client() was never called this test.
    _run(notifier_mod.close_redis_client())


def test_call_internal_returns_parsed_json(monkeypatch):
    _reset_client_singleton(monkeypatch)
    calls = []
    monkeypatch.setattr(
        notifier_mod, "get_client",
        lambda: _FakeAsyncClient(calls, response_payload={"success": True, "data": {"x": 1}}),
    )
    notifier = NodeNotifier()
    result = _run(notifier.call_internal("sess1", "/internal/algo/foo", {"a": 1}))

    assert result == {"success": True, "data": {"x": 1}}
    assert len(calls) == 1
    method, url, payload, _headers, timeout = calls[0]
    assert method == "POST"
    assert url.endswith("/internal/algo/foo")
    assert payload == {"a": 1}
    assert timeout == 45.0


def test_call_internal_returns_error_dict_on_exception(monkeypatch):
    _reset_client_singleton(monkeypatch)
    monkeypatch.setattr(
        notifier_mod, "get_client",
        lambda: _FakeAsyncClient([], raise_exc=RuntimeError("boom")),
    )
    notifier = NodeNotifier()
    result = _run(notifier.call_internal("sess1", "/internal/algo/foo", {"a": 1}))

    assert result["success"] is False
    assert "boom" in result["error"]


def test_get_client_returns_same_instance_across_calls(monkeypatch):
    _reset_client_singleton(monkeypatch)
    c1 = notifier_mod.get_client()
    c2 = notifier_mod.get_client()
    assert c1 is c2
    _run(notifier_mod.close_client())


def test_close_client_clears_singleton_so_next_get_client_builds_fresh(monkeypatch):
    _reset_client_singleton(monkeypatch)
    c1 = notifier_mod.get_client()
    _run(notifier_mod.close_client())
    assert notifier_mod._client is None
    c2 = notifier_mod.get_client()
    assert c1 is not c2
    _run(notifier_mod.close_client())


def test_close_client_is_a_noop_when_never_created(monkeypatch):
    _reset_client_singleton(monkeypatch)
    # Must not raise even though get_client() was never called this test.
    _run(notifier_mod.close_client())
