from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path.cwd()
DEFAULT_CONFIG = {
    "review": {
        "name": "BioForge structural review",
        "comment_marker": "<!-- bioforge-structural-review -->",
        "comment_title": "BioForge structural review",
        "group_by": "file",
        "max_items": 100,
        "max_items_per_file": 20,
        "write_job_summary": True,
        "success_message": "BioForge Review Bot: wangwang! 🐶 He's happy. No structural problems found.",
        "failure_message": "BioForge Review Bot found blocking structural issues. Please fix the items below.",
    },
    "checks": {
        "ruff": {
            "enabled": True,
            "blocking": True,
            "output": ".review/ruff.json",
        },
        "ruff_format": {
            "enabled": True,
            "blocking": True,
            "output": ".review/ruff-format.txt",
            "exit_code_output": ".review/ruff-format.exitcode",
        },
    },
}


def load_config() -> dict[str, Any]:
    config_path = ROOT / ".review.yml"
    if not config_path.exists():
        return DEFAULT_CONFIG

    with config_path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}

    config = DEFAULT_CONFIG.copy()
    config["review"] = {**DEFAULT_CONFIG["review"], **loaded.get("review", {})}
    config["checks"] = {**DEFAULT_CONFIG["checks"], **loaded.get("checks", {})}
    return config


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in {path}, got {type(data).__name__}")

    return data


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def read_exit_code(path: Path) -> int:
    if not path.exists():
        return 0

    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return 0

    try:
        return int(raw)
    except ValueError:
        return 1


def write_github_output(name: str, value: str | int | bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return

    normalized = str(value).lower() if isinstance(value, bool) else str(value)

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"{name}={normalized}\n")


def append_job_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(markdown)
        f.write("\n")


def format_diagnostic(diagnostic: dict[str, Any]) -> str:
    filename = diagnostic.get("filename", "<unknown>")
    location = diagnostic.get("location") or {}
    row = location.get("row", "?")
    column = location.get("column", "?")
    code = diagnostic.get("code") or "RUFF"
    message = diagnostic.get("message") or ""

    return f"- `{code}` at `{filename}:{row}:{column}`: {message}"


def render_ruff_section(
    diagnostics: list[dict[str, Any]],
    max_items: int,
    max_items_per_file: int,
) -> str:
    if not diagnostics:
        return "## Ruff check\n\nNo Ruff lint issues found.\n"

    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for diagnostic in diagnostics:
        filename = diagnostic.get("filename", "<unknown>")
        by_file[filename].append(diagnostic)

    lines: list[str] = []
    lines.append(f"## Ruff check\n\nFound **{len(diagnostics)}** issue(s).\n")

    shown_total = 0

    for filename in sorted(by_file):
        if shown_total >= max_items:
            break

        items = by_file[filename]
        lines.append(f"\n### `{filename}` ({len(items)})\n")

        shown_in_file = 0
        for diagnostic in items:
            if shown_total >= max_items or shown_in_file >= max_items_per_file:
                break

            lines.append(format_diagnostic(diagnostic))
            shown_total += 1
            shown_in_file += 1

        omitted_in_file = len(items) - shown_in_file
        if omitted_in_file > 0:
            lines.append(f"- ... {omitted_in_file} more issue(s) omitted in this file.")

    omitted_total = len(diagnostics) - shown_total
    if omitted_total > 0:
        lines.append(f"\n> {omitted_total} issue(s) omitted because the comment reached the display limit.")

    lines.append("")
    return "\n".join(lines)


def render_format_section(format_failed: bool, format_output: str) -> str:
    if not format_failed:
        return "## Ruff format\n\nFormatting check passed.\n"

    output = format_output.strip()
    if len(output) > 4000:
        output = output[:4000] + "\n... output truncated ..."

    return "\n".join(
        [
            "## Ruff format",
            "",
            "Formatting check failed. Run this locally:",
            "",
            "```bash",
            "ruff format .",
            "```",
            "",
            "<details>",
            "<summary>Formatter output</summary>",
            "",
            "```text",
            output,
            "```",
            "",
            "</details>",
            "",
        ]
    )


def main() -> None:
    config = load_config()
    review_config = config["review"]
    checks_config = config["checks"]

    review_dir = ROOT / ".review"
    review_dir.mkdir(parents=True, exist_ok=True)

    marker = review_config["comment_marker"]
    title = review_config["comment_title"]
    max_items = int(review_config.get("max_items", 100))
    max_items_per_file = int(review_config.get("max_items_per_file", 20))

    ruff_config = checks_config.get("ruff", {})
    ruff_enabled = bool(ruff_config.get("enabled", True))
    ruff_blocking = bool(ruff_config.get("blocking", True))
    ruff_output_path = ROOT / ruff_config.get("output", ".review/ruff.json")

    format_config = checks_config.get("ruff_format", {})
    format_enabled = bool(format_config.get("enabled", True))
    format_blocking = bool(format_config.get("blocking", True))
    format_output_path = ROOT / format_config.get("output", ".review/ruff-format.txt")
    format_exit_code_path = ROOT / format_config.get(
        "exit_code_output",
        ".review/ruff-format.exitcode",
    )

    ruff_diagnostics = read_json_list(ruff_output_path) if ruff_enabled else []
    format_output = read_text(format_output_path) if format_enabled else ""
    format_failed = read_exit_code(format_exit_code_path) != 0 if format_enabled else False

    ruff_failed = len(ruff_diagnostics) > 0
    blocking_failed = (ruff_blocking and ruff_failed) or (format_blocking and format_failed)

    status = "failed" if blocking_failed else "passed"
    emoji = "❌" if blocking_failed else "✅"

    success_message = review_config.get(
        "success_message",
        "BioForge Review Bot: wangwang! 🐶 He's happy. No structural problems found.",
    )
    failure_message = review_config.get(
        "failure_message",
        "BioForge Review Bot found blocking structural issues. Please fix the items below.",
    )

    main_message = failure_message if blocking_failed else success_message

    lines: list[str] = [
        marker,
        f"# {title} {emoji}",
        "",
        f"Status: **{status}**",
        "",
        f"> {main_message}",
        "",
        "This is an automated structural review. It checks low-level Python issues only; it is not a functional code review.",
        "",
        "## Summary",
        "",
        f"- Ruff lint: **{len(ruff_diagnostics)}** issue(s)",
        f"- Ruff format: **{'failed' if format_failed else 'passed'}**",
        "",
    ]

    if ruff_enabled:
        lines.append(render_ruff_section(ruff_diagnostics, max_items, max_items_per_file))

    if format_enabled:
        lines.append(render_format_section(format_failed, format_output))

    lines.extend(
        [
            "---",
            "Local commands:",
            "",
            "```bash",
            "ruff check .",
            "ruff format --check .",
            "```",
            "",
        ]
    )

    comment = "\n".join(lines)

    comment_path = review_dir / "comment.md"
    comment_path.write_text(comment, encoding="utf-8")

    write_github_output("ruff_issue_count", len(ruff_diagnostics))
    write_github_output("format_failed", format_failed)
    write_github_output("blocking_failed", blocking_failed)
    write_github_output("comment_path", str(comment_path))

    if review_config.get("write_job_summary", True):
        append_job_summary(comment)


if __name__ == "__main__":
    main()
