"""命令行入口：批量生成预设工况的表格、曲线和明细输出。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cable_tension.paper import reproduce_paper  # noqa: E402


def main() -> int:
    """运行全部预设工况，并生成输入表、结果表、图和单工况目录。"""

    parser = argparse.ArgumentParser(description="Generate submarine cable tension result tables and figures.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "paper_reproduction",
        help="Output directory.",
    )
    parser.add_argument("--points", type=int, default=201, help="Profile points per case.")
    args = parser.parse_args()

    result = reproduce_paper(args.output, points=args.points)
    print(f"paper_reproduction_dir: {result.output_dir}")
    print(f"case_count: {result.case_count}")
    print(f"inputs: {result.output_dir / 'inputs' / 'cases.csv'}")
    print(f"tables: {result.output_dir / 'tables'}")
    print(f"figures: {result.output_dir / 'figures'}")
    print(f"input_output: {result.output_dir / 'INPUT_OUTPUT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
