"""Run the Python research pipeline in a deterministic file-name order.

Default stages:
    source/cleaning/*.py
    source/analysis/*.py

Optional collection stage:
    python replication/run_all.py --include-collection

Files beginning with an underscore are skipped. Any failed script stops the
pipeline immediately and returns a non-zero exit code.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 本项目特有：数据采集阶段里有一个脚本会真实调用付费 API。
# 自动化复现绝不能误触发它（会产生费用、且会污染“任务—时段”的随机安排），
# 因此把它排除在 run_all 之外，必须由人工带参数显式执行。
# 具体命令见 docs/00_work-plan.md §8.
COLLECTION_MANUAL_ONLY = {"03_run_experiment.py"}


def ensure_output_directories() -> None:
    for relative_path in (
        "outputs/data",
        "outputs/figures",
        "outputs/tables",
        "outputs/models",
        "outputs/other",
    ):
        (PROJECT_ROOT / relative_path).mkdir(parents=True, exist_ok=True)


def scripts_in(relative_directory: str, exclude: set[str] | None = None) -> list[Path]:
    directory = PROJECT_ROOT / relative_directory
    exclude = exclude or set()
    return sorted(
        path
        for path in directory.glob("*.py")
        if path.is_file() and not path.name.startswith("_") and path.name not in exclude
    )


def run_stage(label: str, relative_directory: str, exclude: set[str] | None = None) -> None:
    scripts = scripts_in(relative_directory, exclude)
    print(f"\n=== {label} ===")
    if exclude:
        skipped = sorted(exclude)
        print(f"跳过（需人工执行）：{', '.join(skipped)}")
    if not scripts:
        print(f"No Python scripts found in {relative_directory}; skipping.")
        return

    for script in scripts:
        relative_script = script.relative_to(PROJECT_ROOT)
        print(f"Running {relative_script}")
        subprocess.run(
            [sys.executable, str(script)],
            cwd=PROJECT_ROOT,
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the research pipeline.")
    parser.add_argument(
        "--include-collection",
        action="store_true",
        help="Run data/collection/*.py before cleaning and analysis.",
    )
    args = parser.parse_args()

    ensure_output_directories()

    if args.include_collection:
        run_stage("DATA COLLECTION", "data/collection", exclude=COLLECTION_MANUAL_ONLY)

    run_stage("DATA CLEANING", "source/cleaning")
    run_stage("DATA ANALYSIS", "source/analysis")
    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()
