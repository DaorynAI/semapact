from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def _top_level_module(package_name: str) -> str:
    parts = package_name.split(".")
    if len(parts) >= 2 and parts[0] == "semapact":
        return parts[1]
    if package_name == "semapact":
        return "root"
    return package_name or "root"


def build_summary(xml_path: Path) -> str:
    root = ET.parse(xml_path).getroot()
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for package in root.findall(".//package"):
        module = _top_level_module(package.get("name", ""))
        for line in package.findall("./classes/class/lines/line"):
            stats[module][0] += 1
            if int(line.get("hits", "0")) > 0:
                stats[module][1] += 1

    rows = [
        "## Test Coverage",
        "",
        "| Module | Statements | Missed | Coverage |",
        "| --- | ---: | ---: | ---: |",
    ]

    total_statements = 0
    total_covered = 0
    for module in sorted(stats):
        statements, covered = stats[module]
        missed = statements - covered
        pct = (covered / statements * 100) if statements else 100.0
        rows.append(f"| `{module}` | {statements} | {missed} | {pct:.1f}% |")
        total_statements += statements
        total_covered += covered

    total_missed = total_statements - total_covered
    total_pct = (total_covered / total_statements * 100) if total_statements else 100.0
    rows.extend(
        [
            f"| **TOTAL** | **{total_statements}** | **{total_missed}** | **{total_pct:.1f}%** |",
            "",
            "Detailed per-file and line coverage is available in the `coverage-report` artifact.",
        ]
    )
    return "\n".join(rows)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: coverage_summary.py <coverage.xml>", file=sys.stderr)
        return 2

    xml_path = Path(sys.argv[1])
    if not xml_path.is_file():
        print(f"coverage XML not found: {xml_path}", file=sys.stderr)
        return 1

    print(build_summary(xml_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
