from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


@dataclass(frozen=True)
class UpstreamResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


def forward_json(
    endpoint: str,
    payload: dict[str, object],
    incoming_headers: dict[str, str],
    *,
    upstream_base_url: str,
    timeout_seconds: float,
) -> UpstreamResponse:
    parsed = urlparse(upstream_base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("upstream_base_url must start with http:// or https://")
    endpoint_parts = urlparse(endpoint)
    if (
        endpoint_parts.scheme
        or endpoint_parts.netloc
        or endpoint_parts.params
        or endpoint_parts.query
        or endpoint_parts.fragment
    ):
        raise ValueError("endpoint must be path-only")

    url = urljoin(upstream_base_url.rstrip("/") + "/", endpoint.lstrip("/"))
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    headers = {"content-type": "application/json"}
    for key, value in incoming_headers.items():
        if key.lower() not in HOP_BY_HOP:
            headers[key] = value

    request = Request(url=url, data=body_bytes, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return UpstreamResponse(
                status_code=response.status,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=response.read(),
            )
    except HTTPError as error:
        return UpstreamResponse(
            status_code=error.code,
            headers={k.lower(): v for k, v in (error.headers or {}).items()},
            body=error.read(),
        )
