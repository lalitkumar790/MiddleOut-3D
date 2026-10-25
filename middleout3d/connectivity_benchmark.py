"""Benchmark source vs BFS triangle-face ordering for every MO3D coder."""
from __future__ import annotations

import csv
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .codec import (
    AUTO_ORDERINGS,
    CODEC_METHODS,
    FACE_CODING_OPTIONS,
    decode_mesh,
    encode_mesh,
    load_mesh,
    reorder_mesh,
)


def _timed(function: Callable[[], Any], repeats: int) -> tuple[Any, float]:
    samples: list[float] = []
    value: Any = None
    for _ in range(repeats):
        start = time.perf_counter()
        value = function()
        samples.append(time.perf_counter() - start)
    return value, statistics.median(samples)


def _canonical_faces(faces: np.ndarray) -> list[tuple[int, int, int]]:
    """Canonicalize row order and cyclic start while preserving face winding."""
    canonical = []
    for face in np.asarray(faces, dtype=np.int64):
        a, b, c = (int(x) for x in face)
        canonical.append(min((a, b, c), (b, c, a), (c, a, b)))
    return sorted(canonical)


def _benchmark_one(
    vertices: np.ndarray,
    faces: np.ndarray,
    ordered_vertices: np.ndarray,
    ordered_faces: np.ndarray,
    bits: int,
    repeats: int,
    method: str,
    vertex_ordering: str,
    face_ordering: str,
) -> dict[str, Any]:
    payload, encode_seconds = _timed(
        lambda: encode_mesh(
            vertices,
            faces,
            bits=bits,
            method=method,
            ordering=vertex_ordering,
            face_ordering=face_ordering,
        ),
        repeats,
    )
    (decoded_vertices, decoded_faces, header), decode_seconds = _timed(
        lambda: decode_mesh(payload), repeats
    )
    errors = np.linalg.norm(decoded_vertices - ordered_vertices, axis=1)
    spans = ordered_vertices.max(axis=0) - ordered_vertices.min(axis=0)
    error_bound = float(np.linalg.norm(spans / (2 * ((1 << bits) - 1))))
    topology_exact = _canonical_faces(decoded_faces) == _canonical_faces(ordered_faces)
    return {
        "bytes": len(payload),
        "encode_median_ms": round(encode_seconds * 1000, 4),
        "decode_median_ms": round(decode_seconds * 1000, 4),
        "max_vertex_error": float(errors.max()) if errors.size else 0.0,
        "rmse_vertex_distance": float(np.sqrt(np.mean(errors ** 2))) if errors.size else 0.0,
        "error_bound": error_bound,
        "error_budget_met": bool(not errors.size or float(errors.max()) <= error_bound * 1.0001 + 1e-12),
        "topology_exact": topology_exact,
        "header_face_ordering": header.get("face_ordering", "source"),
    }


def benchmark_connectivity_file(path: Path, bits: int = 16, repeats: int = 1) -> list[dict[str, Any]]:
    vertices, faces, _ = load_mesh(path)
    output: list[dict[str, Any]] = []
    for vertex_ordering in AUTO_ORDERINGS:
        ordered_vertices, ordered_faces, _ = reorder_mesh(vertices, faces, vertex_ordering)
        for method in CODEC_METHODS:
            candidates: dict[str, Any] = {}
            for face_ordering in FACE_CODING_OPTIONS:
                candidates[face_ordering] = _benchmark_one(
                    vertices,
                    faces,
                    ordered_vertices,
                    ordered_faces,
                    bits,
                    repeats,
                    method,
                    vertex_ordering,
                    face_ordering,
                )
            source = candidates["source"]
            rotate = candidates["rotate"]
            rotate_dp = candidates["rotate_dp"]
            bfs = candidates["bfs"]
            output.append({
                "mesh": path.name,
                "source_file_bytes": path.stat().st_size,
                "vertices": int(len(vertices)),
                "triangles": int(len(faces)),
                "position_bits": bits,
                "repeats": repeats,
                "method": method,
                "vertex_ordering": vertex_ordering,
                "source_face_stream": source,
                "rotate_face_stream": rotate,
                "rotate_dp_face_stream": rotate_dp,
                "bfs_face_stream": bfs,
                "rotate_size_reduction_vs_source_pct": round(
                    (1 - rotate["bytes"] / source["bytes"]) * 100, 4
                ) if source["bytes"] else None,
                "rotate_dp_size_reduction_vs_source_pct": round(
                    (1 - rotate_dp["bytes"] / source["bytes"]) * 100, 4
                ) if source["bytes"] else None,
                "rotate_dp_size_reduction_vs_rotate_pct": round(
                    (1 - rotate_dp["bytes"] / rotate["bytes"]) * 100, 4
                ) if rotate["bytes"] else None,
                "bfs_size_reduction_vs_source_pct": round(
                    (1 - bfs["bytes"] / source["bytes"]) * 100, 4
                ) if source["bytes"] else None,
            })
    return output


def benchmark_connectivity_directory(
    input_dir: str | Path,
    output_json: str | Path,
    bits: int = 16,
    repeats: int = 1,
) -> dict[str, Any]:
    if not isinstance(bits, int) or isinstance(bits, bool) or not 8 <= bits <= 24:
        raise ValueError("bits must be an integer from 8 through 24")
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    supported = {".obj", ".ply", ".stl", ".off"}
    files = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in supported)
    if not files:
        raise ValueError(f"No supported mesh files found in {input_dir}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in files:
        try:
            results.extend(benchmark_connectivity_file(path, bits, repeats))
        except Exception as exc:
            errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})
    if not results:
        raise RuntimeError("No connectivity comparisons completed; inspect the recorded errors")

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results:
        key = (row["vertex_ordering"], row["method"])
        entry = grouped.setdefault(key, {
            "vertex_ordering": row["vertex_ordering"],
            "method": row["method"],
            "mesh_count": 0,
            "source_total_bytes": 0,
            "rotate_total_bytes": 0,
            "rotate_dp_total_bytes": 0,
            "bfs_total_bytes": 0,
            "source_error_checks_passed": True,
            "rotate_error_checks_passed": True,
            "rotate_dp_error_checks_passed": True,
            "bfs_error_checks_passed": True,
            "source_topology_checks_passed": True,
            "rotate_topology_checks_passed": True,
            "rotate_dp_topology_checks_passed": True,
            "bfs_topology_checks_passed": True,
        })
        entry["mesh_count"] += 1
        entry["source_total_bytes"] += row["source_face_stream"]["bytes"]
        entry["rotate_total_bytes"] += row["rotate_face_stream"]["bytes"]
        entry["rotate_dp_total_bytes"] += row["rotate_dp_face_stream"]["bytes"]
        entry["bfs_total_bytes"] += row["bfs_face_stream"]["bytes"]
        entry["source_error_checks_passed"] &= row["source_face_stream"]["error_budget_met"]
        entry["rotate_error_checks_passed"] &= row["rotate_face_stream"]["error_budget_met"]
        entry["rotate_dp_error_checks_passed"] &= row["rotate_dp_face_stream"]["error_budget_met"]
        entry["bfs_error_checks_passed"] &= row["bfs_face_stream"]["error_budget_met"]
        entry["source_topology_checks_passed"] &= row["source_face_stream"]["topology_exact"]
        entry["rotate_topology_checks_passed"] &= row["rotate_face_stream"]["topology_exact"]
        entry["rotate_dp_topology_checks_passed"] &= row["rotate_dp_face_stream"]["topology_exact"]
        entry["bfs_topology_checks_passed"] &= row["bfs_face_stream"]["topology_exact"]
    aggregates = list(grouped.values())
    for row in aggregates:
        row["rotate_size_reduction_vs_source_pct"] = round(
            (1 - row["rotate_total_bytes"] / row["source_total_bytes"]) * 100, 4
        ) if row["source_total_bytes"] else None
        row["rotate_dp_size_reduction_vs_source_pct"] = round(
            (1 - row["rotate_dp_total_bytes"] / row["source_total_bytes"]) * 100, 4
        ) if row["source_total_bytes"] else None
        row["rotate_dp_size_reduction_vs_rotate_pct"] = round(
            (1 - row["rotate_dp_total_bytes"] / row["rotate_total_bytes"]) * 100, 4
        ) if row["rotate_total_bytes"] else None
        row["bfs_size_reduction_vs_source_pct"] = round(
            (1 - row["bfs_total_bytes"] / row["source_total_bytes"]) * 100, 4
        ) if row["source_total_bytes"] else None

    report = {
        "project": "MiddleOut-3D",
        "experiment": "source vs rotation-only vs BFS face stream coding",
        "report_version": 1,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
        "configuration": {
            "position_bits": bits,
            "repeats": repeats,
            "methods": list(CODEC_METHODS),
            "vertex_orderings": list(AUTO_ORDERINGS),
            "face_orderings": list(FACE_CODING_OPTIONS),
            "timing_statistic": "median wall-clock time via perf_counter",
            "warmup": "not explicitly separated",
        },
        "results": results,
        "aggregate": aggregates,
        "errors": errors,
        "interpretation_note": (
            "Greedy rotation chooses the locally cheapest cyclic start. rotate_dp uses a "
            "three-state dynamic program to minimize total raw signed-varint byte count "
            "for fixed face order. Size-reduction metrics are emitted consistently in both "
            "per-mesh rows and aggregate rows. BFS traverses the triangle dual graph. Triangle "
            "winding is preserved; reported bytes include the complete MO3D bitstream."
        ),
    }
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    csv_path = output_json.with_suffix(".csv")
    columns = [
        "mesh", "method", "vertex_ordering",
        "source_bytes", "rotate_bytes", "rotate_dp_bytes", "bfs_bytes",
        "rotate_size_reduction_vs_source_pct", "rotate_dp_size_reduction_vs_source_pct",
        "rotate_dp_size_reduction_vs_rotate_pct", "bfs_size_reduction_vs_source_pct",
        "source_encode_median_ms", "rotate_encode_median_ms", "rotate_dp_encode_median_ms", "bfs_encode_median_ms",
        "source_decode_median_ms", "rotate_decode_median_ms", "rotate_dp_decode_median_ms", "bfs_decode_median_ms",
        "source_max_vertex_error", "rotate_max_vertex_error", "rotate_dp_max_vertex_error", "bfs_max_vertex_error",
        "source_error_budget_met", "rotate_error_budget_met", "rotate_dp_error_budget_met", "bfs_error_budget_met",
        "source_topology_exact", "rotate_topology_exact", "rotate_dp_topology_exact", "bfs_topology_exact",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in results:
            writer.writerow({
                "mesh": row["mesh"],
                "method": row["method"],
                "vertex_ordering": row["vertex_ordering"],
                "source_bytes": row["source_face_stream"]["bytes"],
                "rotate_bytes": row["rotate_face_stream"]["bytes"],
                "rotate_dp_bytes": row["rotate_dp_face_stream"]["bytes"],
                "bfs_bytes": row["bfs_face_stream"]["bytes"],
                "rotate_size_reduction_vs_source_pct": row["rotate_size_reduction_vs_source_pct"],
                "rotate_dp_size_reduction_vs_source_pct": row["rotate_dp_size_reduction_vs_source_pct"],
                "rotate_dp_size_reduction_vs_rotate_pct": row["rotate_dp_size_reduction_vs_rotate_pct"],
                "bfs_size_reduction_vs_source_pct": row["bfs_size_reduction_vs_source_pct"],
                "source_encode_median_ms": row["source_face_stream"]["encode_median_ms"],
                "rotate_encode_median_ms": row["rotate_face_stream"]["encode_median_ms"],
                "rotate_dp_encode_median_ms": row["rotate_dp_face_stream"]["encode_median_ms"],
                "bfs_encode_median_ms": row["bfs_face_stream"]["encode_median_ms"],
                "source_decode_median_ms": row["source_face_stream"]["decode_median_ms"],
                "rotate_decode_median_ms": row["rotate_face_stream"]["decode_median_ms"],
                "rotate_dp_decode_median_ms": row["rotate_dp_face_stream"]["decode_median_ms"],
                "bfs_decode_median_ms": row["bfs_face_stream"]["decode_median_ms"],
                "source_max_vertex_error": row["source_face_stream"]["max_vertex_error"],
                "rotate_max_vertex_error": row["rotate_face_stream"]["max_vertex_error"],
                "rotate_dp_max_vertex_error": row["rotate_dp_face_stream"]["max_vertex_error"],
                "bfs_max_vertex_error": row["bfs_face_stream"]["max_vertex_error"],
                "source_error_budget_met": row["source_face_stream"]["error_budget_met"],
                "rotate_error_budget_met": row["rotate_face_stream"]["error_budget_met"],
                "rotate_dp_error_budget_met": row["rotate_dp_face_stream"]["error_budget_met"],
                "bfs_error_budget_met": row["bfs_face_stream"]["error_budget_met"],
                "source_topology_exact": row["source_face_stream"]["topology_exact"],
                "rotate_topology_exact": row["rotate_face_stream"]["topology_exact"],
                "rotate_dp_topology_exact": row["rotate_dp_face_stream"]["topology_exact"],
                "bfs_topology_exact": row["bfs_face_stream"]["topology_exact"],
            })
    return {
        "report": str(output_json),
        "csv": str(csv_path),
        "files_found": len(files),
        "comparisons": len(results),
        "errors": len(errors),
    }
