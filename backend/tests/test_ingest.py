"""Unit tests for the ingestion pipeline (contract / normalization / adapters).

These exercise the highest-risk code for silent data bugs: converting raw
portal rows into the normalized RawProject schema. No database is touched.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.contract import DataConfidence, ProjectStatus, RawProject
from ingest.normalize import (
    canonical_sector,
    canonical_state,
    derive_scale,
    to_iso_date,
)
from ingest.sources.csv_file import CsvFileIngestor
from ingest.sources.data_gov_in import DataGovInIngestor


class NormalizeTests(unittest.TestCase):
    def test_canonical_sector_groups_aliases(self):
        cases = {
            "Road": "Transport",
            "Highways": "Transport",
            "Road Transport and Highways": "Transport",
            "Metro": "Transport",
            "Railways": "Transport",
            "Power": "Energy",
            "Solar": "Energy",
            "Irrigation": "Water",
            "Drinking Water": "Water",
            "Telecom": "Communication",
            "Housing": "Social Infrastructure",
            "Coal": "Mining",
            "Something Unknown": "Other",
            "": "Other",
        }
        for raw, expected in cases.items():
            self.assertEqual(canonical_sector(raw), expected, raw)

    def test_derive_scale_thresholds(self):
        self.assertIsNone(derive_scale(None))
        self.assertIsNone(derive_scale(50))
        self.assertEqual(derive_scale(100).value, "MEDIUM")
        self.assertEqual(derive_scale(999.9).value, "MEDIUM")
        self.assertEqual(derive_scale(1000.0).value, "MEDIUM")
        self.assertEqual(derive_scale(1000.01).value, "LARGE")
        self.assertEqual(derive_scale(61940).value, "LARGE")

    def test_canonical_state_aliases(self):
        self.assertEqual(canonical_state("Orissa"), "Odisha")
        self.assertEqual(canonical_state("Uttaranchal"), "Uttarakhand")
        self.assertEqual(canonical_state("NCT Of Delhi"), "Delhi")
        self.assertEqual(canonical_state("Maharashtra"), "Maharashtra")
        self.assertEqual(canonical_state(""), "Unknown")

    def test_to_iso_date_formats(self):
        self.assertEqual(to_iso_date("2021-04-15"), "2021-04-15")
        self.assertEqual(to_iso_date("15/04/2021"), "2021-04-15")
        self.assertEqual(to_iso_date("2021"), "2021-01-01")
        self.assertIsNone(to_iso_date(None))
        self.assertIsNone(to_iso_date("not-a-date"))


class CsvIngestorTests(unittest.TestCase):
    def setUp(self):
        self.ingestor = CsvFileIngestor("unused.csv", dry_run=True)

    def test_parse_maps_columns_and_defaults(self):
        rows = [
            {
                "project_name": "Sample Bridge",
                "sector": "Road",
                "status": "in progress",
                "agency": "State PWD",
                "state_name": "Orissa",
                "district_name": "Sundargarh",
                "start_date": "01/01/2022",
                "planned_end_date": "31/12/2025",
                "cost_estimate_cr": "450",
                "funding_source": "state_govt",
                "latitude": "22.2",
                "longitude": "84.5",
                "confidence": "official",
            }
        ]
        projects = self.ingestor.parse(rows)
        self.assertEqual(len(projects), 1)
        p = projects[0]
        self.assertEqual(p.name, "Sample Bridge")
        self.assertEqual(p.sector, "Road")
        self.assertEqual(p.stateName, "Orissa")
        self.assertEqual(p.status, ProjectStatus.ONGOING)
        self.assertEqual(p.startDate, "2022-01-01")
        self.assertEqual(p.plannedEndDate, "2025-12-31")
        self.assertEqual(p.costEstimateCr, 450.0)
        self.assertEqual(p.fundingSource.value, "STATE_GOVT")
        self.assertEqual(p.confidence, DataConfidence.OFFICIAL)
        self.assertEqual(p.scale().value, "MEDIUM")

    def test_parse_rejects_missing_name(self):
        with self.assertRaises(ValueError):
            self.ingestor.parse([{"project_name": "", "sector": "Other"}])


class DataGovInTests(unittest.TestCase):
    def test_parse_maps_common_portal_columns(self):
        ingestor = DataGovInIngestor()
        row = {
            "project_name": "Expressway Corridor",
            "sector_name": "Road Transport",
            "implementing_agency": "NHAI",
            "state_name": "Uttar Pradesh",
            "approved_project_cost": "12500",
            "start_date": "2020-06-01",
            "commencement_date": "2020-06-01",
            "_id": "abc123",
        }
        projects = ingestor.parse([row])
        self.assertEqual(len(projects), 1)
        p = projects[0]
        self.assertEqual(p.externalRef, "abc123")
        # An "approved" cost is the SANCTIONED figure. It must land in
        # originalCostCr, not be reused as the revised estimate - reusing one
        # source column for both is what made cost overrun identically zero.
        self.assertEqual(p.originalCostCr, 12500.0)
        self.assertIsNone(p.costEstimateCr)
        self.assertEqual(p.sector, "Road Transport")
        self.assertEqual(p.stateName, "Uttar Pradesh")
        self.assertEqual(p.scale().value, "LARGE")

    def test_fetch_requires_config(self):
        ingestor = DataGovInIngestor(resource_id="", api_key="")
        with self.assertRaises(RuntimeError):
            ingestor.fetch()


class ContractTests(unittest.TestCase):
    def test_raw_project_validation(self):
        with self.assertRaises(Exception):
            RawProject(name="x", sector="Other", stateName="Unknown", retrievedDate="2026-01-01")

    def test_raw_project_dates_must_be_iso(self):
        p = RawProject(
            name="Valid Project",
            sector="Other",
            stateName="Unknown",
            retrievedDate="2026-01-01",
            startDate="2021-01-01",
        )
        self.assertEqual(p.startDate, "2021-01-01")


if __name__ == "__main__":
    unittest.main()