"""Regression tests for the connectivity benchmark's JSON/CSV schema."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import trimesh

from middleout3d.connectivity_benchmark import benchmark_connectivity_directory


class ConnectivityBenchmarkSchemaTests(unittest.TestCase):
    def test_rotate_dp_size_metrics_exist_in_rows_aggregates_and_csv(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            meshes = root / "meshes"
            meshes.mkdir()
            trimesh.creation.box().export(meshes / "box.obj", file_type="obj")
            report_path = root / "connectivity.json"

            outcome = benchmark_connectivity_directory(
                meshes, report_path, bits=8, repeats=1
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(outcome["errors"], 0)
            self.assertEqual(report["errors"], [])
            self.assertGreater(outcome["comparisons"], 0)

            row_fields = (
                "rotate_dp_size_reduction_vs_source_pct",
                "rotate_dp_size_reduction_vs_rotate_pct",
            )
            for row in report["results"]:
                for field in row_fields:
                    with self.subTest(mesh=row["mesh"], method=row["method"],
                                      ordering=row["vertex_ordering"], field=field):
                        self.assertIn(field, row)
                        self.assertIsNotNone(row[field])

            aggregate_fields = row_fields + (
                "rotate_dp_error_checks_passed",
                "rotate_dp_topology_checks_passed",
            )
            self.assertTrue(report["aggregate"])
            for row in report["aggregate"]:
                for field in aggregate_fields:
                    self.assertIn(field, row)
                self.assertTrue(row["rotate_dp_error_checks_passed"])
                self.assertTrue(row["rotate_dp_topology_checks_passed"])

            csv_path = report_path.with_suffix(".csv")
            with csv_path.open(newline="", encoding="utf-8") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(len(csv_rows), len(report["results"]))
            for field in row_fields:
                self.assertIn(field, csv_rows[0])
                self.assertNotEqual(csv_rows[0][field], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
