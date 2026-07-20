"""SPARQL UPDATE client.

A small, reusable HTTP client for sending ``INSERT DATA`` (and other)
SPARQL UPDATE operations to the GraphDB endpoint (design.md D6). This is
the shared write path across chunks 6-8, not a Go-client counterpart —
the graph-write contract is language-neutral over HTTP.
"""

from __future__ import annotations

from msr_extraction.config import Config

# Case-insensitive substrings that identify an RDF4J/GraphDB ShaclSail
# validation-report rejection body (as opposed to a generic transport
# error). Matching is deliberately over-inclusive within error responses
# only — see `update()`.
_VALIDATION_REPORT_MARKERS = (
    "validationreport",
    "sh:result",
    '"conforms"',
    "shacl",
)


class ValidationError(Exception):
    """A GraphDB commit-time SHACL rejection, carrying the RDF4J validation report."""

    def __init__(self, report: str, *, status_code: int | None = None) -> None:
        super().__init__("SPARQL update rejected by SHACL validation")
        self.report = report
        self.status_code = status_code


class SparqlClient:
    """Thin HTTP client for a single SPARQL UPDATE endpoint."""

    def __init__(self, endpoint: str, *, timeout: float = 30.0) -> None:
        """Store the target SPARQL UPDATE endpoint URL and request timeout."""
        self.endpoint = endpoint
        self.timeout = timeout

    def update(self, sparql_update: str) -> None:
        """POST a SPARQL UPDATE string to the endpoint.

        Sends ``update=<sparql_update>`` form-encoded to ``self.endpoint``.
        On a 2xx response this returns ``None`` (unchanged from before).
        On an error response, if the body looks like an RDF4J/GraphDB
        ShaclSail validation report (see ``_VALIDATION_REPORT_MARKERS``),
        raises :class:`ValidationError` carrying that report so callers can
        distinguish a SHACL rejection from a generic transport error.
        Any other error response falls through to
        ``response.raise_for_status()``, raising the usual
        ``httpx.HTTPStatusError``.

        # deferred import: `import httpx` belongs inside this function body —
        # httpx is added to pyproject by a parallel build-wiring change and
        # is not available at module import time in this branch.
        """
        import httpx

        response = httpx.post(
            self.endpoint,
            data={"update": sparql_update},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        if response.is_error:
            body = response.text or ""
            lowered = body.lower()
            if any(marker in lowered for marker in _VALIDATION_REPORT_MARKERS):
                raise ValidationError(report=body, status_code=response.status_code)
            response.raise_for_status()

    @classmethod
    def from_config(cls, config: Config) -> SparqlClient:
        """Build a SparqlClient targeting ``config.sparql_update_endpoint``."""
        return cls(config.sparql_update_endpoint)
