"""DeepSeek V4 Flash disambiguation layer (design.md D5).

A schema-constrained call for spans the lexical layers (expanded exact
matching, the formula normalizer, the bounded ``rapidfuzz`` fallback) leave
unresolved. The model receives the span's sentence context on top of the
cached KG-schema prompt (D6) and must reply with JSON that either links the
span to an *existing* IRI or declares it novel.

DeepSeek's OpenAI-compatible JSON output mode (``response_format={"type":
"json_object"}``) guarantees syntactically valid JSON but, unlike
Gemini/OpenAI strict schemas, does not enforce field-level structure — so
this module always validates the parsed object app-side: a shape check and
the known-IRI check. The model can therefore only map a span to an existing
entity, never mint a new IRI as a link; any anomaly (malformed JSON, an
unknown IRI, an explicit novel declaration, or an unexpected shape) is
recorded as "novel" and never raises.

The client is injected via the :class:`Completer` protocol and is stubbed in
every test (design.md D5/D10) — this module never contacts a live model
under test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from msr_extraction.config import Config


class Completer(Protocol):
    """Anything that can complete a system/user prompt pair into text."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return the model's raw text response to the given prompts."""
        ...


class FlashClient:
    """Injected OpenAI-compatible client for DeepSeek V4 Flash (design.md D5).

    Configured via ``DEEPSEEK_BASE_URL``/``LLM_MODEL_EXTRACT`` (see
    :class:`msr_extraction.config.Config`). Satisfies the :class:`Completer`
    protocol so it is interchangeable with the stub used in every test.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Store the DeepSeek endpoint, model name, and request settings."""
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: Config) -> FlashClient | None:
        """Build a configured client, or ``None`` when DeepSeek isn't set up.

        ``config.deepseek_base_url`` defaults to the empty string so
        ``make link`` works without DeepSeek credentials — callers should
        skip the disambiguation layer entirely when this returns ``None``.
        """
        if not config.deepseek_base_url:
            return None
        return cls(
            config.deepseek_base_url,
            config.llm_model_extract,
            api_key=config.deepseek_api_key or None,
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Call DeepSeek's chat-completions endpoint and return the reply text.

        Uses JSON output mode (``response_format={"type": "json_object"}``),
        which guarantees syntactically valid JSON but not field-level
        structure — callers (see :func:`disambiguate`) must still validate
        the parsed shape and contents.

        # deferred import: `import openai` belongs inside this method body so
        # the module imports with zero third-party deps at import time.
        """
        import openai

        client = openai.OpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "unused",
            timeout=self.timeout,
        )
        response = client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content


@dataclass(frozen=True)
class Disambiguation:
    """The validated outcome of a Flash disambiguation call (design.md D5)."""

    status: Literal["linked", "novel"]
    target_iri: str | None  # set iff status == "linked"


def _build_user_prompt(surface: str, sentence: str) -> str:
    """Build the per-span user prompt appended to the cached KG-schema prefix.

    Includes the literal word "json" and a shape example, as DeepSeek's JSON
    output mode requires the word "json" to appear somewhere in the prompt.
    """
    return (
        "Disambiguate the following entity mention against the knowledge "
        "graph schema and known entities above.\n\n"
        f'Sentence: "{sentence}"\n'
        f'Mention: "{surface}"\n\n'
        "Respond with a single JSON object — either:\n"
        '  {"link": "<existing IRI from the schema above>"}\n'
        "or, if the mention does not match any existing entity:\n"
        '  {"novel": true}\n\n'
        "Return only the json object, no other text."
    )


def disambiguate(
    surface: str,
    sentence: str,
    prompt_prefix: str,
    known_iris: set[str],
    client: Completer,
) -> Disambiguation:
    """Resolve a span via Flash, validated against the known-IRI set.

    Builds a user prompt from ``sentence``/``surface`` instructing the model
    to return JSON that either links to an existing IRI or declares the span
    novel, calls ``client.complete(prompt_prefix, user_prompt)``, and
    validates the result:

    - malformed JSON, a non-object payload, or an unrecognized shape ->
      ``Disambiguation("novel", None)``;
    - an explicit (truthy) ``novel`` declaration ->
      ``Disambiguation("novel", None)``;
    - a ``link`` whose IRI is in ``known_iris`` ->
      ``Disambiguation("linked", iri)``;
    - a ``link`` whose IRI is *not* in ``known_iris`` -> rejected, falls
      through to ``Disambiguation("novel", None)`` — never a silent link.

    Never raises: any anomaly is treated as novel (design.md D5/D10).
    """
    user_prompt = _build_user_prompt(surface, sentence)

    try:
        raw = client.complete(prompt_prefix, user_prompt)
    except Exception:
        return Disambiguation("novel", None)

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return Disambiguation("novel", None)

    if not isinstance(parsed, dict):
        return Disambiguation("novel", None)

    if parsed.get("novel"):
        return Disambiguation("novel", None)

    link = parsed.get("link")
    if isinstance(link, str) and link in known_iris:
        return Disambiguation("linked", link)

    # Missing/invalid shape, or a link IRI outside the known set: reject
    # rather than silently link (design.md D5 — never invent an IRI).
    return Disambiguation("novel", None)
