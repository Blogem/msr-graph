"""``sparql.py`` ValidationError tests (task 8.15, tasks.md 5.7).

Pins ``SparqlClient.update()``'s classification of a GraphDB/RDF4J SHACL
commit-rejection response as a typed ``ValidationError`` (carrying the
report + status code), distinct from a generic transport error (which
still raises via ``response.raise_for_status()``), and confirms the
success path (2xx) is unchanged.

Hermetic: monkeypatches ``httpx.post`` (patched by name, since
``sparql.py`` does a lazy ``import httpx`` inside ``update()`` -- module
patching of an attribute already imported at collection time would miss
it) with a fake response; no network.
"""

from __future__ import annotations

import httpx
import pytest

from msr_extraction.sparql import SparqlClient, ValidationError

ENDPOINT = "http://graphdb.example/repositories/msr/statements"


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        self.is_error = status_code >= 400

    def raise_for_status(self) -> None:
        if self.is_error:
            raise httpx.HTTPStatusError(
                f"error {self.status_code}",
                request=httpx.Request("POST", ENDPOINT),
                response=httpx.Response(self.status_code, text=self.text),
            )


def test_shacl_validation_report_response_raises_validation_error(monkeypatch) -> None:
    body = (
        '{"conforms": false} sh:ValidationReport sh:result '
        "PropertyMeasurementShape violation"
    )
    fake_response = _FakeResponse(400, body)
    monkeypatch.setattr("httpx.post", lambda *a, **k: fake_response)

    client = SparqlClient(ENDPOINT)
    with pytest.raises(ValidationError) as exc_info:
        client.update("INSERT DATA { GRAPH <urn:msr:data> { msrd:x a msr:Thing . } }")

    assert exc_info.value.report == body
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "marker_body",
    [
        '{"conforms": false}',
        "sh:ValidationReport",
        "sh:result",
    ],
)
def test_any_shacl_marker_in_body_raises_validation_error(monkeypatch, marker_body) -> None:
    fake_response = _FakeResponse(400, marker_body)
    monkeypatch.setattr("httpx.post", lambda *a, **k: fake_response)

    client = SparqlClient(ENDPOINT)
    with pytest.raises(ValidationError):
        client.update("INSERT DATA { GRAPH <urn:msr:data> { msrd:x a msr:Thing . } }")


def test_generic_server_error_without_shacl_marker_is_not_a_validation_error(
    monkeypatch,
) -> None:
    fake_response = _FakeResponse(500, "Internal Server Error")
    monkeypatch.setattr("httpx.post", lambda *a, **k: fake_response)

    client = SparqlClient(ENDPOINT)
    with pytest.raises(Exception) as exc_info:
        client.update("INSERT DATA { GRAPH <urn:msr:data> { msrd:x a msr:Thing . } }")

    assert not isinstance(exc_info.value, ValidationError)


def test_success_response_returns_none_and_does_not_raise(monkeypatch) -> None:
    fake_response = _FakeResponse(200, "")
    monkeypatch.setattr("httpx.post", lambda *a, **k: fake_response)

    client = SparqlClient(ENDPOINT)
    result = client.update("INSERT DATA { GRAPH <urn:msr:data> { msrd:x a msr:Thing . } }")
    assert result is None
