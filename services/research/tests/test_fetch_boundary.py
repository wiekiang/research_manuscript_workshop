"""External-access boundary 1 (PRODUCT_SPEC §8): the controlled fetcher cannot be steered to private targets."""

from __future__ import annotations

import httpx
import pytest

from rp_contracts.netpolicy import FetchBlocked, validate_url
from rp_contracts.scanning import scan
from rp_research.fetch.fetcher import ControlledFetcher, FetchFailed


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/", "http://[::1]/", "http://10.1.2.3/", "http://192.168.0.1/",
    "http://172.16.5.4/", "http://169.254.169.254/latest/meta-data/", "http://metadata.google.internal/",
    "http://0.0.0.0/", "http://2130706433/", "http://0x7f.0.0.1/", "http://127.1/", "http://[::ffff:10.0.0.1]/",
    "http://100.64.0.1/", "file:///etc/passwd", "gopher://example.org/", "https://user:pw@example.org/",
    "https://example.org:22/", "http://printer.local/", "http://service.internal/",
])
def test_url_policy_rejects(url):
    with pytest.raises(FetchBlocked):
        validate_url(url)


def test_url_policy_accepts_public():
    assert validate_url("https://Conference.Example.org/CFP?x=1")[0] == "https://conference.example.org/CFP?x=1"


def resolver_for(mapping):
    calls = []

    async def resolve(host, port):
        calls.append(host)
        val = mapping[host]
        return val.pop(0) if isinstance(val, list) and val and isinstance(val[0], list) else val

    resolve.calls = calls
    return resolve


def handler_seen(responses):
    seen = []

    def handle(request: httpx.Request):
        seen.append(request)
        return responses(request)

    return handle, seen


async def test_dns_resolving_to_private_is_blocked():
    handle, seen = handler_seen(lambda r: httpx.Response(200, text="x"))
    f = ControlledFetcher(resolver=resolver_for({"evil.example.org": ["10.0.0.5"]}), transport=httpx.MockTransport(handle))
    with pytest.raises(FetchBlocked) as exc:
        await f.fetch("https://evil.example.org/cfp")
    assert exc.value.reason == "private_address" and seen == []


async def test_any_private_address_in_answer_set_blocks():
    f = ControlledFetcher(resolver=resolver_for({"mixed.example.org": ["93.184.216.34", "127.0.0.1"]}),
                          transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(FetchBlocked):
        await f.fetch("https://mixed.example.org/")


async def test_redirect_to_private_target_is_blocked_at_the_hop():
    def respond(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    handle, seen = handler_seen(respond)
    f = ControlledFetcher(resolver=resolver_for({"conf.example.org": ["93.184.216.34"]}), transport=httpx.MockTransport(handle))
    with pytest.raises(FetchBlocked) as exc:
        await f.fetch("https://conf.example.org/cfp")
    assert exc.value.reason == "private_address"
    assert len(seen) == 1, "the private hop is never requested"


async def test_connection_is_pinned_to_vetted_ip_with_original_host_header():
    handle, seen = handler_seen(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text="<p>ok</p>"))
    f = ControlledFetcher(resolver=resolver_for({"conf.example.org": ["93.184.216.34"]}), transport=httpx.MockTransport(handle))
    res = await f.fetch("https://conf.example.org/cfp")
    req = seen[0]
    assert req.url.host == "93.184.216.34", "the request goes to the vetted address, not a second DNS lookup"
    assert req.headers["host"] == "conf.example.org"
    assert req.extensions.get("sni_hostname") == "conf.example.org"
    assert res.hops[0].ip == "93.184.216.34" and res.content == b"<p>ok</p>"


async def test_redirect_chain_revalidates_each_hop():
    def respond(request):
        if request.headers["host"] == "a.example.org":
            return httpx.Response(301, headers={"location": "https://b.example.org/final"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="final")

    handle, seen = handler_seen(respond)
    resolver = resolver_for({"a.example.org": ["93.184.216.34"], "b.example.org": ["151.101.1.1"]})
    f = ControlledFetcher(resolver=resolver, transport=httpx.MockTransport(handle))
    res = await f.fetch("https://a.example.org/")
    assert [h.ip for h in res.hops] == ["93.184.216.34", "151.101.1.1"]
    assert res.final_url == "https://b.example.org/final" and resolver.calls == ["a.example.org", "b.example.org"]


async def test_size_and_type_caps():
    big = ControlledFetcher(resolver=resolver_for({"x.example.org": ["93.184.216.34"]}), max_bytes=100,
                            transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"},
                                                                                   content=b"a" * 1000)))
    with pytest.raises(FetchBlocked) as exc:
        await big.fetch("https://x.example.org/")
    assert exc.value.reason == "too_large"
    exe = ControlledFetcher(resolver=resolver_for({"x.example.org": ["93.184.216.34"]}),
                            transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "application/x-msdownload"},
                                                                                   content=b"MZ")))
    with pytest.raises(FetchBlocked) as exc:
        await exe.fetch("https://x.example.org/")
    assert exc.value.reason == "content_type_not_allowed"


async def test_upstream_errors_are_classified_for_retry():
    f = ControlledFetcher(resolver=resolver_for({"x.example.org": ["93.184.216.34"]}),
                          transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "30"})))
    with pytest.raises(FetchFailed) as exc:
        await f.fetch("https://x.example.org/")
    assert exc.value.retryable and exc.value.retry_after == 30
    f = ControlledFetcher(resolver=resolver_for({"x.example.org": ["93.184.216.34"]}),
                          transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(FetchFailed) as exc:
        await f.fetch("https://x.example.org/")
    assert not exc.value.retryable


async def test_robots_disallow_is_respected_for_automated_fetches():
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="ok")

    f = ControlledFetcher(resolver=resolver_for({"x.example.org": ["93.184.216.34"]}), transport=httpx.MockTransport(respond))
    with pytest.raises(FetchBlocked) as exc:
        await f.fetch("https://x.example.org/private/cfp", check_robots=True)
    assert exc.value.reason == "robots_disallowed"
    assert (await f.fetch("https://x.example.org/cfp", check_robots=True)).robots == "allowed"


def test_quarantine_scan_flags():
    assert scan(b"%PDF-1.7 /Encrypt 1 0 R", "application/pdf").verdict == "rejected"
    assert scan(b"%PDF-1.7 /JavaScript (app.alert)", "application/pdf").verdict == "suspicious"
    assert not scan(b"%PDF-1.4", "text/html").matches_declared
    report = scan(b"<html><script>x</script></html>", "text/html")
    assert report.verdict == "clean" and any("script" in f for f in report.flags)
