"""命令行入口：运行一个命名铺缆工况。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cable_tension.cases import get_case, list_cases  # noqa: E402
from cable_tension.io import write_result  # noqa: E402
from cable_tension.solver import solve_case  # noqa: E402


def main() -> int:
    """解析命令行参数、调用求解器，并写出稳定命名的输出文件。"""

    parser = argparse.ArgumentParser(
        description="Run one submarine cable laying tension case.",
    )
    parser.add_argument("--case", help="Case name, for example la_accel_200m")
    parser.add_argument("--points", type=int, default=201, help="Number of profile points")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory. Default: output/<case>.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available cases.",
    )
    args = parser.parse_args()

    if args.list:
        for name in list_cases():
            print(name)
        return 0
    if not args.case:
        parser.error("--case is required unless --list is used")

    case = get_case(args.case)
    result = solve_case(case, points=args.points)
    output_dir = args.output if args.output is not None else ROOT / "output" / case.name
    written = write_result(result, output_dir)

    print(f"case: {result.case_name}")
    print(f"top_tension_final_n: {result.top_tension_final_n:.3f}")
    print(f"summary_csv: {written.summary_csv}")
    print(f"profile_csv: {written.profile_csv}")
    print(f"profile_svg: {written.profile_svg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
