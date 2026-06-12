from __future__ import annotations

import argparse
from pathlib import Path

from app.graph import ShoppingAssistant


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Student scaffold CLI.")
    parser.add_argument("--question", help="Run one question through the graph.")
    parser.add_argument("--test-file", default="../data/test.json")
    parser.add_argument("--output-dir", default="artifacts/batch")
    parser.add_argument("--trace-file", default=None)
    parser.add_argument("--batch", action="store_true", help="Run batch evaluation")
    parser.add_argument("--filter", nargs="*", help="Limit batch to specific IDs, e.g. Q01 Q05")
    return parser


def main() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args()

    if args.batch:
        from evaluate import run_eval
        run_eval(
            test_file=Path(args.test_file),
            output_dir=Path(args.output_dir),
            test_filter=args.filter,
        )
    elif args.question:
        assistant = ShoppingAssistant()
        trace_path = Path(args.trace_file) if args.trace_file else None
        res = assistant.ask(args.question, trace_file=trace_path)

        # ── Print trace summary ──
        print("\n╔══════════════════════════════════════════════════╗")
        print("║              📋 TRACE SUMMARY                   ║")
        print("╠══════════════════════════════════════════════════╣")
        for entry in res.get("trace", []):
            node = entry.get("node", "?")
            elapsed = entry.get("elapsed_s", "?")
            tool_calls = entry.get("tool_calls", [])
            tools_str = f" | tools: {len(tool_calls)}" if tool_calls else ""
            print(f"║  {node:<25} {elapsed:>6}s{tools_str:<12} ║")
        print("╚══════════════════════════════════════════════════╝")

        # ── Print final answer ──
        print("\n╔══════════════════════════════════════════════════╗")
        print("║              📝 FINAL ANSWER                    ║")
        print("╚══════════════════════════════════════════════════╝")
        print(res.get("final_answer", ""))
    else:
        print("Please provide --question or --batch.")


if __name__ == "__main__":
    main()
