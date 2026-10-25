"""Complete-payload benchmark for geometry-conditioned distance-ranked connectivity."""
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

from .codec import CodecError, decode_mesh, encode_mesh, load_mesh, reorder_mesh


def _timed(function: Callable[[], Any], repeats: int) -> tuple[Any, float]:
    samples: list[float] = []
    value: Any = None
    for _ in range(repeats):
        start = time.perf_counter()
        value = function()
        samples.append(time.perf_counter() - start)
    return value, statistics.median(samples)


def _canonical_oriented_faces(faces: np.ndarray) -> list[tuple[int, int, int]]:
    """Ignore row order and cyclic start, but preserve triangle winding."""
    canonical = []
    for raw_face in np.asarray(faces, dtype=np.int64):
        a, b, c = (int(value) for value in raw_face)
        canonical.append(min((a, b, c), (b, c, a), (c, a, b)))
    return sorted(canonical)


def _benchmark_candidate(
    vertices: np.ndarray,
    faces: np.ndarray,
    bits: int,
    repeats: int,
    method: str,
    ordering: str,
) -> dict[str, Any]:
    ordered_vertices, ordered_faces, _ = reorder_mesh(vertices, faces, ordering)
    payload, encode_seconds = _timed(
        lambda: encode_mesh(
            vertices, faces, bits=bits, method=method, ordering=ordering,
            face_ordering="source",
        ),
        repeats,
    )
    (decoded_vertices, decoded_faces, header), decode_seconds = _timed(
        lambda: decode_mesh(payload), repeats
    )
    errors = np.linalg.norm(decoded_vertices - ordered_vertices, axis=1)
    spans = ordered_vertices.max(axis=0) - ordered_vertices.min(axis=0)
    error_bound = float(np.linalg.norm(spans / (2 * ((1 << bits) - 1))))
    topology_exact = (
        _canonical_oriented_faces(decoded_faces)
        == _canonical_oriented_faces(ordered_faces)
    )
    return {
        "bytes": len(payload),
        "coordinate_stream_bytes": header["coordinate_stream_bytes"],
        "connectivity_stream_bytes": header["face_stream_bytes"],
        "encode_median_ms": round(encode_seconds * 1000, 4),
        "decode_median_ms": round(decode_seconds * 1000, 4),
        "max_vertex_error": float(errors.max()) if errors.size else 0.0,
        "rmse_vertex_distance": float(np.sqrt(np.mean(errors ** 2))) if errors.size else 0.0,
        "error_bound": error_bound,
        "error_budget_met": bool(
            not errors.size
            or float(errors.max()) <= error_bound * 1.0001 + 1e-12
        ),
        "topology_exact": topology_exact,
        "format_version": header["version"],
        "coordinate_coder": header.get("coordinate_coder"),
        "connectivity_coder": header.get("connectivity_coder", "delta-zigzag-varint-zlib"),
    }


def _compare_one(
    vertices: np.ndarray,
    faces: np.ndarray,
    path: Path,
    bits: int,
    repeats: int,
    ordering: str,
) -> dict[str, Any]:
    baseline = _benchmark_candidate(vertices, faces, bits, repeats, "baseline", ordering)
    ranked = _benchmark_candidate(
        vertices, faces, bits, repeats, "distance_ranked_connectivity", ordering
    )
    local_ranked = _benchmark_candidate(
        vertices, faces, bits, repeats, "distance_ranked_local_connectivity", ordering
    )
    return {
        "mesh": path.name,
        "source_file_bytes": path.stat().st_size,
        "vertices": int(len(vertices)),
        "triangles": int(len(faces)),
        "position_bits": bits,
        "repeats": repeats,
        "vertex_ordering": ordering,
        "baseline": baseline,
        "distance_ranked": ranked,
        "local_distance_ranked": local_ranked,
        "size_reduction_vs_baseline_pct": round(
            (1 - ranked["bytes"] / baseline["bytes"]) * 100, 4
        ) if baseline["bytes"] else None,
        "connectivity_reduction_vs_baseline_pct": round(
            (1 - ranked["connectivity_stream_bytes"] / baseline["connectivity_stream_bytes"]) * 100,
            4,
        ) if baseline["connectivity_stream_bytes"] else None,
        "local_size_reduction_vs_baseline_pct": round(
            (1 - local_ranked["bytes"] / baseline["bytes"]) * 100, 4
        ) if baseline["bytes"] else None,
        "local_size_reduction_vs_global_ranked_pct": round(
            (1 - local_ranked["bytes"] / ranked["bytes"]) * 100, 4
        ) if ranked["bytes"] else None,
    }


def benchmark_ranked_connectivity_directory(
    input_dir: str | Path,
    output_json: str | Path,
    bits: int = 16,
    repeats: int = 3,
) -> dict[str, Any]:
    """Compare baseline and distance-ranked connectivity under identical precision."""
    if not isinstance(bits, int) or isinstance(bits, bool) or not 8 <= bits <= 24:
        raise ValueError("bits must be an integer from 8 through 24")
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    supported = {".obj", ".ply", ".stl", ".off"}
    files = sorted(
        path for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in supported
    )
    if not files:
        raise ValueError(f"No supported mesh files found in {input_dir}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in files:
        try:
            vertices, faces, _ = load_mesh(path)
        except Exception as exc:
            errors.append({"file": str(path), "ordering": "n/a", "error": f"{type(exc).__name__}: {exc}"})
            continue
        for ordering in ("source", "bfs", "morton"):
            try:
                row = _compare_one(vertices, faces, path, bits, repeats, ordering)
                results.append(row)
            except Exception as exc:
                errors.append({
                    "file": str(path),
                    "ordering": ordering,
                    "error": f"{type(exc).__name__}: {exc}",
                })

    if not results:
        raise RuntimeError(
            "No paired baseline/distance-ranked connectivity comparisons completed; inspect errors"
        )

    baseline_bytes = sum(row["baseline"]["bytes"] for row in results)
    ranked_bytes = sum(row["distance_ranked"]["bytes"] for row in results)
    local_ranked_bytes = sum(row["local_distance_ranked"]["bytes"] for row in results)
    wins = sum(row["distance_ranked"]["bytes"] < row["baseline"]["bytes"] for row in results)
    ties = sum(row["distance_ranked"]["bytes"] == row["baseline"]["bytes"] for row in results)
    losses = len(results) - wins - ties
    local_wins = sum(row["local_distance_ranked"]["bytes"] < row["baseline"]["bytes"] for row in results)
    local_ties = sum(row["local_distance_ranked"]["bytes"] == row["baseline"]["bytes"] for row in results)
    local_losses = len(results) - local_wins - local_ties
    local_wins_vs_ranked = sum(row["local_distance_ranked"]["bytes"] < row["distance_ranked"]["bytes"] for row in results)
    local_ties_vs_ranked = sum(row["local_distance_ranked"]["bytes"] == row["distance_ranked"]["bytes"] for row in results)
    local_losses_vs_ranked = len(results) - local_wins_vs_ranked - local_ties_vs_ranked
    report = {
        "project": "MiddleOut-3D",
        "experiment": "baseline connectivity vs geometry-conditioned distance-ranked connectivity",
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
            "coordinate_coder_for_both": "absolute-fixed-width-zlib",
            "vertex_orderings": ["source", "bfs", "morton"],
            "timing_statistic": "median wall-clock time via perf_counter",
            "warmup": "not explicitly separated",
            "rank_candidate_set": "global: all vertex IDs except gate endpoints; local: 32 nearest candidates with absolute-ID escape",
            "rank_tie_break": "squared Euclidean distance, then vertex ID",
        },
        "summary": {
            "paired_cases": len(results),
            "baseline_total_bytes": baseline_bytes,
            "distance_ranked_total_bytes": ranked_bytes,
            "local_distance_ranked_total_bytes": local_ranked_bytes,
            "size_reduction_pct": round((1 - ranked_bytes / baseline_bytes) * 100, 4) if baseline_bytes else None,
            "local_size_reduction_pct": round((1 - local_ranked_bytes / baseline_bytes) * 100, 4) if baseline_bytes else None,
            "local_vs_global_ranked_reduction_pct": round((1 - local_ranked_bytes / ranked_bytes) * 100, 4) if ranked_bytes else None,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "local_wins_vs_baseline": local_wins,
            "local_ties_vs_baseline": local_ties,
            "local_losses_vs_baseline": local_losses,
            "local_wins_vs_global_ranked": local_wins_vs_ranked,
            "local_ties_vs_global_ranked": local_ties_vs_ranked,
            "local_losses_vs_global_ranked": local_losses_vs_ranked,
            "mean_baseline_connectivity_bytes": round(statistics.mean(r["baseline"]["connectivity_stream_bytes"] for r in results), 4),
            "mean_ranked_connectivity_bytes": round(statistics.mean(r["distance_ranked"]["connectivity_stream_bytes"] for r in results), 4),
            "all_topology_exact": all(
                r["baseline"]["topology_exact"]
                and r["distance_ranked"]["topology_exact"]
                and r["local_distance_ranked"]["topology_exact"]
                for r in results
            ),
            "all_error_budgets_met": all(
                r["baseline"]["error_budget_met"]
                and r["distance_ranked"]["error_budget_met"]
                and r["local_distance_ranked"]["error_budget_met"]
                for r in results
            ),
        },
        "results": results,
        "errors": errors,
        "interpretation_note": (
            "Global and local distance-ranked connectivity are research adaptations, not reproductions "
            "of the published algorithms. The local variant searches 32 nearby candidates and uses "
            "absolute-ID escapes when needed. Compression is compared on complete MO3D payloads at "
            "the same fixed position precision; unsupported topology is recorded in errors."
        ),
    }
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    csv_path = output_json.with_suffix(".csv")
    columns = [
        "mesh", "vertices", "triangles", "vertex_ordering", "position_bits",
        "baseline_bytes", "distance_ranked_bytes", "size_reduction_vs_baseline_pct",
        "baseline_connectivity_bytes", "distance_ranked_connectivity_bytes", "local_distance_ranked_connectivity_bytes",
        "connectivity_reduction_vs_baseline_pct",
        "baseline_encode_median_ms", "distance_ranked_encode_median_ms", "local_distance_ranked_encode_median_ms",
        "baseline_decode_median_ms", "distance_ranked_decode_median_ms", "local_distance_ranked_decode_median_ms",
        "baseline_max_vertex_error", "distance_ranked_max_vertex_error", "local_distance_ranked_max_vertex_error",
        "baseline_rmse_vertex_distance", "distance_ranked_rmse_vertex_distance", "local_distance_ranked_rmse_vertex_distance",
        "baseline_topology_exact", "distance_ranked_topology_exact", "local_distance_ranked_topology_exact",
        "baseline_error_budget_met", "distance_ranked_error_budget_met", "local_distance_ranked_error_budget_met",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in results:
            b, r, lr = row["baseline"], row["distance_ranked"], row["local_distance_ranked"]
            writer.writerow({
                "mesh": row["mesh"], "vertices": row["vertices"], "triangles": row["triangles"],
                "vertex_ordering": row["vertex_ordering"], "position_bits": bits,
                "baseline_bytes": b["bytes"], "distance_ranked_bytes": r["bytes"],
                "size_reduction_vs_baseline_pct": row["size_reduction_vs_baseline_pct"],
                "baseline_connectivity_bytes": b["connectivity_stream_bytes"],
                "distance_ranked_connectivity_bytes": r["connectivity_stream_bytes"],
                "local_distance_ranked_connectivity_bytes": lr["connectivity_stream_bytes"],
                "connectivity_reduction_vs_baseline_pct": row["connectivity_reduction_vs_baseline_pct"],
                "baseline_encode_median_ms": b["encode_median_ms"],
                "distance_ranked_encode_median_ms": r["encode_median_ms"],
                "local_distance_ranked_encode_median_ms": lr["encode_median_ms"],
                "baseline_decode_median_ms": b["decode_median_ms"],
                "distance_ranked_decode_median_ms": r["decode_median_ms"],
                "local_distance_ranked_decode_median_ms": lr["decode_median_ms"],
                "baseline_max_vertex_error": b["max_vertex_error"],
                "distance_ranked_max_vertex_error": r["max_vertex_error"],
                "local_distance_ranked_max_vertex_error": lr["max_vertex_error"],
                "baseline_rmse_vertex_distance": b["rmse_vertex_distance"],
                "distance_ranked_rmse_vertex_distance": r["rmse_vertex_distance"],
                "local_distance_ranked_rmse_vertex_distance": lr["rmse_vertex_distance"],
                "baseline_topology_exact": b["topology_exact"],
                "distance_ranked_topology_exact": r["topology_exact"],
                "local_distance_ranked_topology_exact": lr["topology_exact"],
                "baseline_error_budget_met": b["error_budget_met"],
                "distance_ranked_error_budget_met": r["error_budget_met"],
                "local_distance_ranked_error_budget_met": lr["error_budget_met"],
            })
    return {
        "report": str(output_json),
        "csv": str(csv_path),
        "files_found": len(files),
        "comparisons": len(results),
        "errors": len(errors),
        "summary": report["summary"],
    }
