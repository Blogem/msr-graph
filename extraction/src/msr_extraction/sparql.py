"""SPARQL UPDATE client.

A small, reusable HTTP client for sending ``INSERT DATA`` (and other)
SPARQL UPDATE operations to the GraphDB endpoint (design.md D6). This is
the shared write path across chunks 6-8, not a Go-client counterpart —
the graph-write contract is language-neutral over HTTP.
"""

from __future__ import annotations

from msr_extraction.config import Config


class SparqlClient:
    """Thin HTTP client for a single SPARQL UPDATE endpoint."""

    def __init__(self, endpoint: str, *, timeout: float = 30.0) -> None:
        """Store the target SPARQL UPDATE endpoint URL and request timeout."""
        self.endpoint = endpoint
        self.timeout = timeout

    def update(self, sparql_update: str) -> None:
        """POST a SPARQL UPDATE string to the endpoint.

        Sends ``update=<sparql_update>`` form-encoded to ``self.endpoint``
        and raises if the response is not a 2xx status.

        # deferred import: `import httpx` belongs inside this function body —
        # httpx is added to pyproject by a parallel build-wiring change and
        # is not available at module import time in this branch.
        """
        raise NotImplementedError("task 7.1")

    @classmethod
    def from_config(cls, config: Config) -> SparqlClient:
        """Build a SparqlClient targeting ``config.sparql_update_endpoint``."""
        return cls(config.sparql_update_endpoint)
