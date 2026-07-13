"""CLI for technical users.

  python -m agent analyze --input <parsed.json | raw.log> [--output analysis.json] [--mock]
  python -m agent demo [--mock] [--sample db_pool|bad_deploy|healthy]
"""

import argparse
import json
import sys
from pathlib import Path

from .adapters import to_parsed_log
from .contracts import AnalysisResult
from .core import analyze
from .providers import get_provider

SAMPLES = {
    "db_pool": "db_pool_exhaustion.log",
    "bad_deploy": "bad_deploy_500s.log",
    "healthy": "healthy_run.log",
}
_SAMPLES_DIR = Path(__file__).parent / "samples"

def _print_report(result: AnalysisResult) -> None:
    try:
        _print_rich(result)
    except ImportError:
        _print_plain(result)


def _print_plain(r: AnalysisResult) -> None:
    line = "=" * 70
    print(line)
    print(f" ROSETTA ANALYSIS — {r.log_source}")
    print(f" status: {r.overall_status.upper()}   "
          f"lines: {r.stats.total_lines}  errors: {r.stats.error_lines}  "
          f"warnings: {r.stats.warning_lines}")
    print(line)
    if not r.incidents:
        print(" No incidents. Nothing actionable in this log.")
    for i, inc in enumerate(r.incidents, 1):
        print(f"\n [{i}] {inc.title}")
        print(f"     severity: {inc.severity}   confidence: {inc.confidence:.0%}")
        if inc.affected_sources:
            print(f"     affected: {', '.join(inc.affected_sources)}")
        if inc.first_seen:
            print(f"     window:   {inc.first_seen} -> {inc.last_seen}")
        print(f"\n     {inc.human_explanation}")
        if inc.possible_solutions:
            print("\n     What to do:")
            for s in inc.possible_solutions:
                print(f"       - {s}")
        if inc.evidence:
            print("\n     Evidence:")
            for ev in inc.evidence:
                print(f"       L{ev.line_number}: {ev.raw_text[:100]}")
    print(f"\n{line}")


def _print_rich(r: AnalysisResult) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    status_color = {"critical": "red", "degraded": "yellow",
                    "healthy": "green", "inconclusive": "cyan"}[r.overall_status]
    console.print(Panel(
        f"[bold {status_color}]{r.overall_status.upper()}[/] - "
        f"{r.stats.total_lines} lines, "
        f"[red]{r.stats.error_lines} errors[/], "
        f"[yellow]{r.stats.warning_lines} warnings[/]",
        title=f"Rosetta Analysis - {r.log_source}", border_style=status_color))

    if not r.incidents:
        console.print("[green]No incidents. Nothing actionable in this log.[/]")

    for inc in r.incidents:
        body = (f"[bold]severity:[/] {inc.severity}   "
                f"[bold]confidence:[/] {inc.confidence:.0%}\n")
        if inc.affected_sources:
            body += f"[bold]affected:[/] {', '.join(inc.affected_sources)}\n"
        if inc.first_seen:
            body += f"[bold]window:[/] {inc.first_seen} -> {inc.last_seen}\n"
        body += f"\n{inc.human_explanation}\n"
        if inc.possible_solutions:
            body += "\n[bold]What to do:[/]\n"
            body += "\n".join(f"  - {s}" for s in inc.possible_solutions)
        console.print(Panel(body, title=inc.title,
                            border_style="red" if inc.severity in ("critical", "high") else "yellow"))
        if inc.evidence:
            t = Table(title="Evidence", show_lines=False, expand=False)
            t.add_column("Line", justify="right", style="cyan")
            t.add_column("Log text", overflow="fold")
            for ev in inc.evidence:
                t.add_row(str(ev.line_number), ev.raw_text[:120])
            console.print(t)


def _cmd_analyze(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: input file not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    data = text
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
            return 2
    parsed = to_parsed_log(data, log_source=path.name)
    result = analyze(parsed, provider=get_provider(mock=args.mock or None))
    if args.output:
        Path(args.output).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"wrote {args.output}")
    _print_report(result)
    return 0 if result.overall_status != "inconclusive" else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    sample = _SAMPLES_DIR / SAMPLES[args.sample]
    print(f"Running bundled sample: {sample.name} "
          f"({'mock' if args.mock else 'live'} provider)\n")
    parsed = to_parsed_log(sample.read_text(encoding="utf-8"), log_source=sample.name)
    result = analyze(parsed, provider=get_provider(mock=args.mock or None))
    _print_report(result)
    return 0


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent",
                                     description="Rosetta log analysis agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_an = sub.add_parser("analyze", help="analyze a parsed JSON or raw log file")
    p_an.add_argument("--input", required=True, help="parsed .json or raw .log file")
    p_an.add_argument("--output", help="write the AnalysisResult JSON here")
    p_an.add_argument("--mock", action="store_true", help="use the offline mock provider")
    p_an.set_defaults(fn=_cmd_analyze)

    p_demo = sub.add_parser("demo", help="run a bundled sample end to end")
    p_demo.add_argument("--sample", choices=sorted(SAMPLES), default="db_pool")
    p_demo.add_argument("--mock", action="store_true", help="use the offline mock provider")
    p_demo.set_defaults(fn=_cmd_demo)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
