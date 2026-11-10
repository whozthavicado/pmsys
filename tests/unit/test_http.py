from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pmsys.core.errors import RateLimited, SchemaDrift, UpstreamError, UpstreamTimeout
from pmsys.core.ids import canonical_json, idem_key
from pmsys.infra.http import (
    DEFAULT_POLICIES,
    IDEMPOTENCY_HEADER,
    HostPolicy,
    RetryingHttpClient,
    TokenBucket,
    TransportError,
    TransportTimeout,
    UrllibTransport,
    backoff_delay,
    parse_retry_after,
)
from tests.unit._httpkit import (
    BASE,
    CONN_ERROR,
    HOST,
    TIMEOUT,
    FakeTimer,
    ok,
    policy,
    script,
    status,
)


def client(
    transport: object, timer: FakeTimer, *, uniform=None, **pol: float
) -> RetryingHttpClient:  # type: ignore[no-untyped-def]
    return RetryingHttpClient(
        transport,  # type: ignore[arg-type]
        {HOST: policy(**pol)},
        timer=timer,
        uniform=uniform or (lambda lo, hi: hi),
    )


# ---------------------------------------------------------------- éxito y construcción de URL


def test_get_returns_json_and_encodes_params_in_given_order() -> None:
    t = script(ok('{"a":[1,2]}'))
    out = client(t, FakeTimer()).get_json(f"{BASE}/x", {"limit": "2", "after_cursor": "c d"})
    assert out == {"a": [1, 2]}
    assert t.sent[0].url == f"{BASE}/x?limit=2&after_cursor=c+d"
    assert t.sent[0].method == "GET"
    assert IDEMPOTENCY_HEADER not in t.sent[0].headers


def test_rejects_non_https_and_unknown_host() -> None:
    c = client(script(), FakeTimer())
    with pytest.raises(ValueError, match="https"):
        c.get_json(f"http://{HOST}/x")
    with pytest.raises(ValueError, match="sin política"):
        c.get_json("https://otro.example.test/x")


def test_non_json_body_is_schema_drift() -> None:
    with pytest.raises(SchemaDrift) as ei:
        client(script(ok("<html>")), FakeTimer()).get_json(f"{BASE}/x")
    assert ei.value.source == HOST


# ---------------------------------------------------------------- reintentos


def test_retries_5xx_timeout_and_connection_error_then_succeeds() -> None:
    t = script(status(503), TIMEOUT, CONN_ERROR, ok())
    timer = FakeTimer()
    assert client(t, timer).get_json(f"{BASE}/x") == {"ok": True}
    assert len(t.sent) == 4
    assert len(timer.sleeps) == 3


def test_exhausted_5xx_raises_upstream_error_after_max_retries_plus_one() -> None:
    t = script(*[status(500)] * 4)
    with pytest.raises(UpstreamError) as ei:
        client(t, FakeTimer()).get_json(f"{BASE}/x")
    assert (ei.value.host, ei.value.status) == (HOST, 500)
    assert len(t.sent) == 4


def test_exhausted_timeout_raises_upstream_timeout() -> None:
    t = script(*[TIMEOUT] * 4)
    with pytest.raises(UpstreamTimeout):
        client(t, FakeTimer()).get_json(f"{BASE}/x")


def test_exhausted_429_raises_rate_limited_with_retry_after() -> None:
    t = script(*[status(429, **{"retry-after": "3"})] * 4)
    with pytest.raises(RateLimited) as ei:
        client(t, FakeTimer()).get_json(f"{BASE}/x")
    assert ei.value.retry_after_s == 3.0
    assert len(t.sent) == 4


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_other_4xx_are_not_retried(code: int) -> None:
    t = script(status(code))
    with pytest.raises(UpstreamError) as ei:
        client(t, FakeTimer()).get_json(f"{BASE}/x")
    assert ei.value.status == code
    assert len(t.sent) == 1


def test_3xx_is_not_followed_nor_retried() -> None:
    t = script(status(302, location="https://evil.example.test/"))
    with pytest.raises(UpstreamError):
        client(t, FakeTimer()).get_json(f"{BASE}/x")
    assert len(t.sent) == 1


def test_zero_retries_means_a_single_attempt() -> None:
    t = script(status(500))
    with pytest.raises(UpstreamError):
        client(t, FakeTimer(), max_retries=0).get_json(f"{BASE}/x")
    assert len(t.sent) == 1


# ---------------------------------------------------------------- backoff, jitter, Retry-After


def test_backoff_uses_uniform_0_to_capped_exponential() -> None:
    calls: list[tuple[float, float]] = []

    def uniform(lo: float, hi: float) -> float:
        calls.append((lo, hi))
        return hi / 2

    t = script(*[status(500)] * 4)
    timer = FakeTimer()
    with pytest.raises(UpstreamError):
        client(t, timer, uniform=uniform, base_delay_s=1.0, max_delay_s=3.0).get_json(f"{BASE}/x")
    assert calls == [(0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]  # 4 se recorta a max_delay_s
    assert timer.sleeps == [0.5, 1.0, 1.5]


def test_retry_after_is_a_floor_for_the_delay() -> None:
    t = script(status(429, **{"retry-after": "7"}), ok())
    timer = FakeTimer()
    client(t, timer, uniform=lambda lo, hi: 0.0, max_delay_s=60.0).get_json(f"{BASE}/x")
    assert timer.sleeps == [7.0]


def test_retry_after_above_max_delay_fails_fast_without_sleeping() -> None:
    t = script(status(429, **{"retry-after": "3600"}), ok())
    timer = FakeTimer()
    with pytest.raises(RateLimited) as ei:
        client(t, timer, max_delay_s=60.0).get_json(f"{BASE}/x")
    assert ei.value.retry_after_s == 3600.0
    assert timer.sleeps == []
    assert len(t.sent) == 1


def test_retry_after_also_applies_to_5xx() -> None:
    t = script(status(503, **{"retry-after": "5"}), ok())
    timer = FakeTimer()
    client(t, timer, uniform=lambda lo, hi: 0.0).get_json(f"{BASE}/x")
    assert timer.sleeps == [5.0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3", 3.0), (" 2.5 ", 2.5), ("0", 0.0), (None, None), ("-1", None), ("inf", None),
     ("Wed, 21 Oct 2026 07:28:00 GMT", None), ("", None)],
)  # fmt: skip
def test_parse_retry_after(raw: str | None, expected: float | None) -> None:
    assert parse_retry_after(raw) == expected


@given(
    attempt=st.integers(0, 40),
    base=st.floats(0, 100),
    cap=st.floats(0, 1000),
    u=st.floats(0, 1),
)
def test_property_delay_is_within_zero_and_cap(
    attempt: int, base: float, cap: float, u: float
) -> None:
    pol = HostPolicy(host=HOST, max_req=1, window_s=1.0, base_delay_s=base, max_delay_s=cap)
    d = backoff_delay(pol, attempt, lambda lo, hi: lo + u * (hi - lo))
    assert 0.0 <= d <= cap


@given(retries=st.integers(0, 6), fail=st.sampled_from([500, 502, 503]))
def test_property_attempts_never_exceed_max_retries_plus_one(retries: int, fail: int) -> None:
    t = script(*[status(fail)] * (retries + 1))
    with pytest.raises(UpstreamError):
        client(t, FakeTimer(), max_retries=retries).get_json(f"{BASE}/x")
    assert len(t.sent) == retries + 1


# ---------------------------------------------------------------- token bucket


def test_bucket_allows_burst_then_waits_for_refill() -> None:
    timer = FakeTimer()
    b = TokenBucket(policy(max_req=3, window_s=3.0), timer)  # 1 token/s
    for _ in range(3):
        b.acquire()
    assert timer.sleeps == []
    b.acquire()
    assert timer.now == pytest.approx(1.0)


def test_bucket_refills_with_elapsed_time_up_to_capacity() -> None:
    timer = FakeTimer()
    b = TokenBucket(policy(max_req=2, window_s=2.0), timer)
    b.acquire()
    b.acquire()
    timer.now += 100.0  # mucho tiempo: no acumula más que la capacidad
    b.acquire()
    b.acquire()
    assert timer.sleeps == []
    b.acquire()
    assert timer.sleeps
    assert timer.now == pytest.approx(101.0)


@given(max_req=st.integers(1, 20), window=st.floats(0.5, 30), n=st.integers(1, 120))
def test_property_bucket_never_exceeds_rate(max_req: int, window: float, n: int) -> None:
    timer = FakeTimer()
    b = TokenBucket(policy(max_req=max_req, window_s=window), timer)
    for _ in range(n):
        b.acquire()
    rate = max_req / window
    # n tokens exigen al menos (n - capacidad) / rate segundos desde el inicio
    assert timer.now >= max(0.0, (n - max_req) / rate) - 1e-6


def test_client_spaces_requests_per_host_independently() -> None:
    other = "otro.example.test"
    pols = {
        HOST: HostPolicy(host=HOST, max_req=1, window_s=10.0),
        other: HostPolicy(host=other, max_req=1000, window_s=1.0),
    }
    timer = FakeTimer()
    t = script(ok(), ok(), ok(), ok())
    c = RetryingHttpClient(t, pols, timer=timer)
    c.get_json(f"https://{other}/a")
    c.get_json(f"https://{other}/b")
    assert timer.sleeps == []  # el otro host no espera por HOST
    c.get_json(f"{BASE}/a")
    c.get_json(f"{BASE}/b")
    assert timer.now == pytest.approx(10.0)


def test_retries_also_consume_tokens() -> None:
    timer = FakeTimer()
    t = script(status(500), status(500), ok())
    c = RetryingHttpClient(
        t, {HOST: policy(max_req=1, window_s=100.0)}, timer=timer, uniform=lambda lo, hi: 0.0
    )
    c.get_json(f"{BASE}/x")
    assert timer.now == pytest.approx(200.0)  # dos esperas de 100 s por token


def test_default_policies_are_half_of_the_verified_limits() -> None:
    by_host = {p.host: p for p in DEFAULT_POLICIES}
    gamma = by_host["gamma-api.polymarket.com"]
    assert gamma.max_req / gamma.window_s == pytest.approx(0.5 * 300 / 10)
    clob = by_host["clob.polymarket.com"]
    assert clob.max_req / clob.window_s == pytest.approx(0.5 * 15000 / 10)
    assert set(by_host) == {
        "gamma-api.polymarket.com", "clob.polymarket.com", "polymarket.com", "api.gdeltproject.org",
    }  # fmt: skip


# ---------------------------------------------------------------- idempotencia


def test_post_sends_same_idempotency_key_on_every_retry() -> None:
    t = script(status(503), TIMEOUT, ok())
    client(t, FakeTimer()).post_json(f"{BASE}/p", {"b": 1, "a": [True]})
    keys = {s.headers[IDEMPOTENCY_HEADER] for s in t.sent}
    assert len(t.sent) == 3
    assert keys == {idem_key("POST", f"{BASE}/p", canonical_json({"a": [True], "b": 1}))}
    assert all(s.body == b'{"a":[true],"b":1}' for s in t.sent)
    assert t.sent[0].headers["Content-Type"] == "application/json"


def test_idempotency_key_is_stable_across_calls_and_differs_by_body_and_url() -> None:
    t = script(ok(), ok(), ok(), ok())
    c = client(t, FakeTimer())
    c.post_json(f"{BASE}/p", {"a": 1})
    c.post_json(f"{BASE}/p", {"a": 1})
    c.post_json(f"{BASE}/p", {"a": 2})
    c.post_json(f"{BASE}/q", {"a": 1})
    k = [s.headers[IDEMPOTENCY_HEADER] for s in t.sent]
    assert k[0] == k[1]
    assert len({k[0], k[2], k[3]}) == 3


def test_idempotency_key_ignores_dict_ordering() -> None:
    t = script(ok(), ok())
    c = client(t, FakeTimer())
    c.post_json(f"{BASE}/p", {"a": 1, "b": 2})
    c.post_json(f"{BASE}/p", {"b": 2, "a": 1})
    assert t.sent[0].headers[IDEMPOTENCY_HEADER] == t.sent[1].headers[IDEMPOTENCY_HEADER]


# ---------------------------------------------------------------- secretos


def test_errors_never_leak_query_string_or_headers() -> None:
    t = script(*[status(500)] * 4)
    c = RetryingHttpClient(
        t,
        {HOST: policy()},
        timer=FakeTimer(),
        headers={"Authorization": "Bearer SECRETO123"},
    )
    with pytest.raises(UpstreamError) as ei:
        c.get_json(f"{BASE}/x", {"api_key": "SECRETO123"})
    assert "SECRETO123" not in str(ei.value)
    assert "api_key" not in str(ei.value)
    assert t.sent[0].headers["Authorization"] == "Bearer SECRETO123"  # sí viaja en la petición


# ---------------------------------------------------------------- transporte urllib (sin red)


class _FakeResp:
    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.headers = headers
        self._body = body

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


class _Opener(urllib.request.OpenerDirector):
    def __init__(self, result: object) -> None:
        super().__init__()
        self.result = result
        self.requests: list[urllib.request.Request] = []

    def open(self, fullurl, data=None, timeout=0):  # type: ignore[no-untyped-def,override]
        self.requests.append(fullurl)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _send(opener: _Opener):  # type: ignore[no-untyped-def]
    return UrllibTransport(opener).send(
        "GET", f"{BASE}/x", headers={"Accept": "application/json"}, body=None, timeout_s=1.0
    )


def test_urllib_transport_maps_success_with_lowercased_headers() -> None:
    op = _Opener(_FakeResp(200, {"Retry-After": "1"}, b"{}"))
    r = _send(op)
    assert (r.status, r.headers, r.body) == (200, {"retry-after": "1"}, b"{}")
    assert op.requests[0].get_method() == "GET"


def test_urllib_transport_returns_http_errors_as_responses() -> None:
    err = urllib.error.HTTPError(f"{BASE}/x", 429, "x", {"Retry-After": "9"}, BytesIO(b"{}"))  # type: ignore[arg-type]
    r = _send(_Opener(err))
    assert (r.status, r.headers["retry-after"]) == (429, "9")


def test_urllib_transport_maps_timeouts_and_connection_errors() -> None:
    with pytest.raises(TransportTimeout):
        _send(_Opener(TimeoutError()))
    with pytest.raises(TransportTimeout):
        _send(_Opener(urllib.error.URLError(TimeoutError())))
    with pytest.raises(TransportError):
        _send(_Opener(urllib.error.URLError(ConnectionRefusedError())))
    with pytest.raises(TransportError):
        _send(_Opener(ConnectionResetError()))


def test_default_urllib_opener_does_not_follow_redirects() -> None:
    from pmsys.infra.http import _NoRedirect

    req = urllib.request.Request(f"{BASE}/x")  # noqa: S310
    handler = _NoRedirect()
    assert (
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.test/") is None
    )  # type: ignore[arg-type]


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_real_transport_cannot_reach_the_network_under_pytest() -> None:
    import pytest_socket

    with pytest.raises(pytest_socket.SocketBlockedError):
        UrllibTransport().send("GET", "https://example.com/", headers={}, body=None, timeout_s=1.0)


# ---------------------------------------------------------------- grabación y replay


def test_replay_serves_synthetic_fixtures_through_the_client() -> None:
    from pmsys.infra.replay import ReplayTransport

    rt = ReplayTransport(Path(__file__).parents[1] / "fixtures" / "http")
    out = client(rt, FakeTimer()).get_json(f"{BASE}/v1/items", {"limit": "2"})
    assert out == {"items": [{"id": "a"}, {"id": "b"}]}
    assert rt.requests == [("GET", f"{BASE}/v1/items?limit=2")]


def test_replay_fixture_429_with_retry_after_drives_the_retry_logic() -> None:
    from pmsys.infra.replay import ReplayTransport

    rt = ReplayTransport(Path(__file__).parents[1] / "fixtures" / "http")
    timer = FakeTimer()
    with pytest.raises(RateLimited) as ei:
        client(rt, timer, uniform=lambda lo, hi: 0.0).get_json(f"{BASE}/v1/limited")
    assert ei.value.retry_after_s == 2.0
    assert timer.sleeps == [2.0, 2.0, 2.0]


def test_replay_missing_fixture_fails_loudly_instead_of_hitting_the_network(tmp_path: Path) -> None:
    from pmsys.infra.replay import FixtureNotFound, ReplayTransport

    with pytest.raises(FixtureNotFound):
        ReplayTransport(tmp_path).send("GET", f"{BASE}/nada", headers={}, body=None, timeout_s=1)


def test_recording_roundtrip_redacts_headers(tmp_path: Path) -> None:
    from pmsys.infra.http import TransportResponse
    from pmsys.infra.replay import RecordingTransport, ReplayTransport

    inner = script(
        TransportResponse(
            200,
            {"content-type": "application/json", "set-cookie": "s=1", "x-token": "T"},
            b'{"k":"\xc3\xa1"}',
        )
    )
    rec = RecordingTransport(inner, tmp_path, recorded_at="2026-11-10T00:00:00Z")
    c = RetryingHttpClient(
        rec, {HOST: policy()}, timer=FakeTimer(), headers={"Authorization": "SECRETO"}
    )
    assert c.get_json(f"{BASE}/r") == {"k": "á"}

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    raw = files[0].read_text(encoding="utf-8")
    for forbidden in ("SECRETO", "set-cookie", "x-token"):
        assert forbidden not in raw
    saved = json.loads(raw)
    assert saved["recorded_at"] == "2026-11-10T00:00:00Z"
    assert saved["synthetic"] is False

    again = ReplayTransport(tmp_path)
    assert c.__class__(again, {HOST: policy()}, timer=FakeTimer()).get_json(f"{BASE}/r") == {
        "k": "á"
    }
