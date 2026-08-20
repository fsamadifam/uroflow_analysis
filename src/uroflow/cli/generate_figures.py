"""Command-line entry point for publication figure generation."""

import argparse
from pathlib import Path
import sys

import pandas as pd

from uroflow.core.project_io import load_project
from uroflow.io.load_csv import load_uroflow_csv
from uroflow.reporting.figures import (
    generate_publication_figures,
    project_to_dataframe,
)


def _load_input(path: Path) -> tuple[pd.DataFrame, object, object]:
    if path.suffix.lower() == ".json":
        project = load_project(str(path))
        timestamp = mass = None
        try:
            timestamp, mass, _acquisition_events, _metadata = load_uroflow_csv(
                project.input_csv_path
            )
        except Exception as exc:
            print(
                "Warning: raw trace could not be loaded; the raw trace figure "
                f"will be skipped ({exc}).",
                file=sys.stderr,
            )
        return project_to_dataframe(project), timestamp, mass
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path), None, None
    raise ValueError("Input must be a saved project JSON or events CSV.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate publication figures from a reviewed uroflow project."
    )
    parser.add_argument("input", type=Path, help="Saved project JSON or events CSV")
    parser.add_argument(
        "-o", "--output", type=Path,
        help="Output directory (default: publication_figures beside the input)",
    )
    parser.add_argument(
        "--formats", nargs="+", choices=("png", "svg", "pdf"),
        default=("png", "svg"),
    )
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args(argv)

    output_dir = args.output or args.input.parent / "publication_figures"
    try:
        data, timestamp, mass = _load_input(args.input)
        paths = generate_publication_figures(
            data,
            output_dir,
            formats=args.formats,
            dpi=args.dpi,
            timestamp=timestamp,
            mass=mass,
        )
    except Exception as exc:
        parser.error(str(exc))

    print(f"Generated {len(paths)} files in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
