"""MSR extraction pipeline scaffold.

Empty package proving the project scaffold builds and runs. The real
extraction pipeline (chunks 5-8) lands in later changes.
"""

import argparse

__all__ = ["main"]


def main() -> int:
    """CLI entry point. Currently a no-op scaffold that only supports --help."""
    parser = argparse.ArgumentParser(
        prog="msr-extraction",
        description="MSR knowledge-graph extraction pipeline (scaffold).",
    )
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
