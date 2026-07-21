"""Minimal, dependency-free text-layer PDF builder for safety-acquisition tests.

Task 8.1/8.2 (openspec/changes/ingest-iaea-safety, spec
``safety-source-acquisition``) need a tiny, committed, offline PDF fixture
to prove ``safety_acquire.extract_pdf_text`` round-trips known text without
any network access, and a multi-page variant to prove section/page
scoping picks the right span. Rather than committing a binary ``.pdf``
blob or adding a new dependency (``reportlab``) outside this change's
``pypdf``/``cryptography`` additions, this module hand-assembles a
byte-exact, byte-offset-correct minimal PDF (one ``/Page`` + one
``/Contents`` stream per page, standard ``Helvetica`` base-14 font --
never a truetype file, so no font-embedding is needed) that ``pypdf``
reads like any other text-layer PDF.

Deliberately stdlib-only. No compression, no cross-reference streams --
just the classic ``xref``/``trailer`` tail so ``pypdf`` never needs its
lenient/recovery parser.
"""

from __future__ import annotations


def _escape_pdf_string(text: str) -> str:
    """Escape ``(``/``)``/``\\`` for a PDF literal string. ASCII-only input assumed."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_text_pdf(pages: list[str]) -> bytes:
    """Build a minimal, valid, single-column text-layer PDF with one line of
    text per page.

    Each page gets its own ``/Contents`` stream drawing ``pages[i]`` at a
    fixed position in 12pt Helvetica. Returns the complete PDF file bytes,
    with a correct ``xref`` table (byte-accurate offsets) so ``pypdf`` (or
    any spec-conformant reader) parses it via the normal path, never the
    damaged-xref recovery scan.
    """
    if not pages:
        raise ValueError("build_text_pdf requires at least one page")

    objects: list[bytes] = []

    # obj 1: Catalog: object numbers are 1-indexed and fixed by convention
    # below, so every cross-reference here is a literal, not derived.
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")

    # obj 2: Pages (Kids filled in once page object numbers are known).
    n = len(pages)
    page_obj_nums = [4 + 2 * i for i in range(n)]
    kids = " ".join(f"{num} 0 R" for num in page_obj_nums)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("latin-1"))

    # obj 3: shared Helvetica font (standard 14, no embedding required).
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # obj 4, 6, 8, ...: Page; obj 5, 7, 9, ...: its Contents stream.
    for i, text in enumerate(pages):
        content_obj_num = page_obj_nums[i] + 1
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_obj_num} 0 R >>"
        ).encode("latin-1")
        objects.append(page_dict)

        stream_body = f"BT /F1 12 Tf 72 720 Td ({_escape_pdf_string(text)}) Tj ET".encode(
            "latin-1"
        )
        content_obj = (
            f"<< /Length {len(stream_body)} >>\nstream\n".encode("latin-1")
            + stream_body
            + b"\nendstream"
        )
        objects.append(content_obj)

    # -- Assemble with byte-accurate offsets -------------------------------
    header = b"%PDF-1.4\n"
    buf = bytearray(header)
    offsets: list[int] = []
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{idx} 0 obj\n".encode("latin-1")
        buf += body
        buf += b"\nendobj\n"

    xref_offset = len(buf)
    total = len(objects) + 1  # +1 for the free-list head entry
    buf += f"xref\n0 {total}\n".encode("latin-1")
    buf += b"0000000000 65535 f \n"
    for offset in offsets:
        buf += f"{offset:010d} 00000 n \n".encode("latin-1")

    buf += (
        f"trailer\n<< /Size {total} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    ).encode("latin-1")

    return bytes(buf)
