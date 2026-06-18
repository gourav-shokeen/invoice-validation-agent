from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

SAMPLE_PATHS = {
    "clean": "samples/clean_invoice.txt",
    "broken": "samples/broken_invoice.txt",
}


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _resolve_source(args: argparse.Namespace) -> Path:
    if args.file:
        path = Path(args.file)
    else:
        path = Path(SAMPLE_PATHS[args.sample or "clean"])
    if not path.exists():
        raise SystemExit(f"Invoice source not found: {path}")
    return path


def _print_final_state(state: dict) -> None:
    print("\n" + "=" * 70)
    print("FINAL STATE")
    print("=" * 70)
    print(f"Status   : {state.get('status')}")
    print(f"Attempts : {state.get('attempts')}")
    print("\nExtracted invoice (structured JSON):")
    print(json.dumps(state.get("extracted"), indent=2, ensure_ascii=False))
    errors = state.get("validation_errors") or []
    print(f"\nValidation errors ({len(errors)}):")
    if errors:
        for err in errors:
            print(f"  - {err}")
    else:
        print("  (none)")
    print("\nSummary:")
    print(state.get("summary"))
    print("=" * 70)


def main(argv: list[str] | None = None) -> int:
    """Run the agent against the chosen invoice and print the final state."""
    load_dotenv()
    _configure_logging()

    parser = argparse.ArgumentParser(
        description="Invoice Validation Agent (LangGraph + Gemini)."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--sample", choices=["clean", "broken"], help="Run a bundled sample invoice."
    )
    group.add_argument("--file", help="Path to an invoice text file.")
    args = parser.parse_args(argv)
    if not args.sample and not args.file:
        args.sample = "clean"

    source = _resolve_source(args)

    # defer heavy imports so --help and argparse errors stay fast
    from .graph import build_graph
    from .nodes import AuthError

    graph = build_graph()

    print("=" * 70)
    print("INVOICE VALIDATION AGENT - compiled LangGraph (mermaid)")
    print("=" * 70)
    print(graph.get_graph().draw_mermaid())
    print("=" * 70)
    print(f"Source: {source}\n")

    initial_state = {
        "raw_text": "",
        "extracted": None,
        "validation_errors": [],
        "status": "pending",
        "attempts": 0,
        "summary": "",
    }
    try:
        final_state = graph.invoke(
            initial_state,
            config={"configurable": {"source_path": str(source)}},
        )
    except AuthError as exc:
        print("\n" + "!" * 70)
        print("FATAL: Gemini authentication/configuration failed. Halting.")
        print(f"Exact error: {exc}")
        print("!" * 70)
        return 2

    _print_final_state(final_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
