"""Ingestion CLI.

Run from the `backend` directory:

    python -m ingest.run --source data_gov_in                 # needs env keys
    python -m ingest.run --source csv_file --file data/sample_projects.csv
    python -m ingest.run --source csv_file --file out.csv --dry-run

Always starts with `--dry-run` on a new source so you can review what would
change before touching the database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running as `python -m ingest.run` from anywhere inside the repo.
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from database import SessionLocal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="GovRisk infrastructure project ingestion")
    parser.add_argument("--source", choices=["data_gov_in", "csv_file"], default="csv_file")
    parser.add_argument("--file", help="Path to CSV/JSON (csv_file source)")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable summary"
    )
    args = parser.parse_args()

    if args.source == "data_gov_in":
        from ingest.sources.data_gov_in import DataGovInIngestor

        ingestor = DataGovInIngestor(dry_run=args.dry_run)
    else:
        if not args.file:
            parser.error("--file is required for the csv_file source")
        from ingest.sources.csv_file import CsvFileIngestor

        ingestor = CsvFileIngestor(args.file, dry_run=args.dry_run)

    db = SessionLocal()
    try:
        summary = ingestor.run(db)
    finally:
        db.close()

    if args.json:
        print(json.dumps(summary.as_dict(), indent=2))
        return

    print(f"\nSource:          {summary.source}")
    print(f"Scope floor:     INR {ingestor.scope.min_cost_cr:g} Cr ({ingestor.scope.label})")
    print(f"Total rows:      {summary.total}")
    print(f"Inserted:        {summary.inserted}")
    print(f"Updated:         {summary.updated}")
    print(f"Skipped:         {summary.skipped}")
    print(f"Rejected:        {summary.rejected}")
    print(f"Failed:          {summary.failed}")
    if args.dry_run:
        print("\n(dry-run - nothing was written)")
    if summary.warnings:
        print(f"\nWarnings ({len(summary.warnings)}):")
        for warning in summary.warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()