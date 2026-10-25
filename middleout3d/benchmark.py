"""Reproducible baseline-vs-Prithvi benchmark across vertex orderings."""
from __future__ import annotations

import csv
import gzip
import json
import platform
import statistics
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Any

import numpy as np

from .codec import CODEC_METHODS, ORDERINGS, decode_mesh, encode_mesh, load_mesh, vertex_order_for_mesh

MESH_EXTENSIONS = {".obj", ".ply", ".stl", ".off"}


def _timed(fn, repeats: int = 3):
    durations = []
    value = None
    for _ in range(repeats):
        start = time.perf_counter()
        value = fn()
        durations.append(time.perf_counter() - start)
    return value, statistics.median(durations)


def _simple_geometry_zlib_reference(vertices: np.ndarray, faces: np.ndarray, bits: int) -> bytes:
    """Reference using identical quantized positions but plain fixed-width face indices."""
    levels = (1 << bits) - 1
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    spans = maxs - mins
    safe_spans = np.where(spans == 0.0, 1.0, spans)
    quantized = np.rint((vertices - mins) / safe_spans * levels).clip(0, levels).astype(np.uint32)
    coord_dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
    coord_blob = zlib.compress(quantized.astype(coord_dtype).tobytes(order="C"), level=6)
    face_blob = zlib.compress(np.asarray(faces, dtype="<u4").tobytes(order="C"), level=6)
    header = {
        "format": "MO3D-REF", "version": 1, "position_bits": bits,
        "vertex_count": int(len(vertices)), "face_count": int(len(faces)),
        "bounds_min": mins.tolist(), "bounds_max": maxs.tolist(),
        "coordinate_stream_bytes": len(coord_blob), "face_stream_bytes": len(face_blob),
        "face_encoding": "fixed-width uint32 triangle indices + zlib",
    }
    header_bytes = json.dumps(header, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return b"MO3DREF1" + struct.pack(">I", len(header_bytes)) + header_bytes + coord_blob + face_blob


def _decode_simple_geometry_zlib_reference(payload: bytes) -> tuple[np.ndarray, np.ndarray]:
    if not payload.startswith(b"MO3DREF1") or len(payload) < 12:
        raise ValueError("invalid reference payload")
    header_len = struct.unpack(">I", payload[8:12])[0]
    header_start, body_start = 12, 12 + header_len
    header = json.loads(payload[header_start:body_start].decode("utf-8"))
    coord_len = int(header["coordinate_stream_bytes"])
    coord_raw = zlib.decompress(payload[body_start:body_start + coord_len])
    face_raw = zlib.decompress(payload[body_start + coord_len:])
    bits = int(header["position_bits"])
    count_v, count_f = int(header["vertex_count"]), int(header["face_count"])
    dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
    q = np.frombuffer(coord_raw, dtype=dtype).astype(np.float64).reshape(count_v, 3)
    mins = np.asarray(header["bounds_min"], dtype=np.float64)
    maxs = np.asarray(header["bounds_max"], dtype=np.float64)
    vertices = mins + (q / ((1 << bits) - 1)) * (maxs - mins)
    faces = np.frombuffer(face_raw, dtype="<u4").astype(np.int64).reshape(count_f, 3)
    return vertices, faces


def _benchmark_coder(
    vertices: np.ndarray, faces: np.ndarray, bits: int, repeats: int, method: str, ordering: str
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """Benchmark one coder/ordering, then map decoded data back to source indexing."""
    payload, encode_seconds = _timed(
        lambda: encode_mesh(vertices, faces, bits=bits, method=method, ordering=ordering), repeats
    )
    (decoded_vertices, decoded_faces, metadata), decode_seconds = _timed(lambda: decode_mesh(payload), repeats)

    # The encoder emits vertices in the requested traversal order. Convert the
    # decoded arrays back to source indices for geometry/topology correctness checks.
    permutation = vertex_order_for_mesh(vertices, faces, ordering)  # new index -> original index
    restored_vertices = np.empty_like(decoded_vertices)
    restored_vertices[permutation] = decoded_vertices
    restored_faces = permutation[decoded_faces]
    errors = np.linalg.norm(restored_vertices - vertices, axis=1)

    metrics = {
        "ordering": ordering,
        "method": method,
        "bytes": len(payload),
        "encode_median_ms": round(encode_seconds * 1000, 4),
        "decode_median_ms": round(decode_seconds * 1000, 4),
        "max_vertex_error": float(errors.max()) if errors.size else 0.0,
        "rmse_vertex_distance": float(np.sqrt(np.mean(errors ** 2))) if errors.size else 0.0,
        "topology_exact": bool(np.array_equal(restored_faces, faces)),
        "format_version": metadata["version"],
        "header_ordering": metadata.get("vertex_ordering", "source"),
        "predictive_vertices": int(metadata.get("tangent_predictive_vertices") or 0),
        "tangent_residual_step": metadata.get("tangent_residual_step"),
    }
    return metrics, decoded_vertices, decoded_faces


def _faces_topology_equivalent(left: np.ndarray, right: np.ndarray) -> bool:
    """Compare triangle connectivity while ignoring face-list order and winding."""
    if left.shape != right.shape:
        return False
    left_sorted = np.sort(np.asarray(left, dtype=np.int64), axis=1)
    right_sorted = np.sort(np.asarray(right, dtype=np.int64), axis=1)
    left_sorted = left_sorted[np.lexsort((left_sorted[:, 2], left_sorted[:, 1], left_sorted[:, 0]))]
    right_sorted = right_sorted[np.lexsort((right_sorted[:, 2], right_sorted[:, 1], right_sorted[:, 0]))]
    return bool(np.array_equal(left_sorted, right_sorted))


def _benchmark_draco(
    vertices: np.ndarray, faces: np.ndarray, bits: int, repeats: int, ordering: str
) -> dict[str, Any]:
    """Benchmark Google's Draco through the optional DracoPy Python wrapper."""
    try:
        import DracoPy
    except ImportError as exc:
        raise RuntimeError(
            "DracoPy is not installed; install requirements-benchmark.txt to run the Draco comparison"
        ) from exc

    ordered_vertices, ordered_faces, permutation = reorder_mesh(vertices, faces, ordering)
    payload, encode_seconds = _timed(
        lambda: DracoPy.encode(
            ordered_vertices,
            faces=ordered_faces,
            quantization_bits=bits,
            compression_level=7,
            preserve_order=True,
        ),
        repeats,
    )
    decoded, decode_seconds = _timed(lambda: DracoPy.decode(payload), repeats)
    decoded_vertices = np.asarray(decoded.points, dtype=np.float64)
    decoded_faces = np.asarray(decoded.faces, dtype=np.int64)
    if decoded_vertices.ndim != 2 or decoded_vertices.shape != ordered_vertices.shape:
        raise ValueError(
            f"Draco decoded vertex shape {decoded_vertices.shape} does not match input {ordered_vertices.shape}"
        )
    if decoded_faces.ndim != 2 or decoded_faces.shape[1] != 3:
        raise ValueError(f"Draco decoded face array has unexpected shape {decoded_faces.shape}")

    restored_vertices = np.empty_like(decoded_vertices)
    restored_vertices[permutation] = decoded_vertices
    restored_faces = permutation[decoded_faces]
    errors = np.linalg.norm(restored_vertices - vertices, axis=1)
    return {
        "ordering": ordering,
        "bytes": len(payload),
        "encode_median_ms": round(encode_seconds * 1000, 4),
        "decode_median_ms": round(decode_seconds * 1000, 4),
        "max_vertex_error": float(errors.max()) if errors.size else 0.0,
        "rmse_vertex_distance": float(np.sqrt(np.mean(errors ** 2))) if errors.size else 0.0,
        "topology_equivalent": _faces_topology_equivalent(restored_faces, faces),
        "topology_exact_face_order": bool(np.array_equal(restored_faces, faces)),
        "quantization_bits": bits,
        "compression_level": 7,
        "ordering": ordering,
    }


def benchmark_file(path: Path, bits: int = 16, repeats: int = 3) -> dict[str, Any]:
    original = path.read_bytes()
    vertices, faces, _ = load_mesh(path)
    gzip_bytes, gzip_seconds = _timed(lambda: gzip.compress(original, compresslevel=6, mtime=0), repeats)
    reference_bytes, reference_seconds = _timed(
        lambda: _simple_geometry_zlib_reference(vertices, faces, bits), repeats
    )
    reference_decoded, reference_decode_seconds = _timed(
        lambda: _decode_simple_geometry_zlib_reference(reference_bytes), repeats
    )

    ordering_results: list[dict[str, Any]] = []
    for ordering in ORDERINGS:
        coder_metrics: dict[str, dict[str, Any]] = {}
        coder_decoded_vertices: dict[str, np.ndarray] = {}
        for method in CODEC_METHODS:
            metrics, decoded_vertices, _ = _benchmark_coder(
                vertices, faces, bits, repeats, method, ordering
            )
            coder_metrics[method] = metrics
            coder_decoded_vertices[method] = decoded_vertices

        baseline_metrics = coder_metrics["baseline"]
        prithvi_metrics = coder_metrics["prithvi"]
        tangent_metrics = coder_metrics["tangent"]
        weighted_metrics = coder_metrics["weighted_tangent"]
        positions_equal = bool(
            np.array_equal(coder_decoded_vertices["baseline"], coder_decoded_vertices["prithvi"])
        )
        draco_metrics = _benchmark_draco(vertices, faces, bits, repeats, ordering)
        result: dict[str, Any] = {
            "ordering": ordering,
            "baseline_bytes": baseline_metrics["bytes"],
            "prithvi_bytes": prithvi_metrics["bytes"],
            "tangent_bytes": tangent_metrics["bytes"],
            "weighted_tangent_bytes": weighted_metrics["bytes"],
            "prithvi_size_reduction_vs_baseline_pct": round(
                (1 - prithvi_metrics["bytes"] / baseline_metrics["bytes"]) * 100, 4
            ) if baseline_metrics["bytes"] else None,
            "tangent_size_reduction_vs_baseline_pct": round(
                (1 - tangent_metrics["bytes"] / baseline_metrics["bytes"]) * 100, 4
            ) if baseline_metrics["bytes"] else None,
            "weighted_tangent_size_reduction_vs_baseline_pct": round(
                (1 - weighted_metrics["bytes"] / baseline_metrics["bytes"]) * 100, 4
            ) if baseline_metrics["bytes"] else None,
            "tangent_size_reduction_vs_prithvi_pct": round(
                (1 - tangent_metrics["bytes"] / prithvi_metrics["bytes"]) * 100, 4
            ) if prithvi_metrics["bytes"] else None,
            "weighted_tangent_size_reduction_vs_prithvi_pct": round(
                (1 - weighted_metrics["bytes"] / prithvi_metrics["bytes"]) * 100, 4
            ) if prithvi_metrics["bytes"] else None,
            "baseline_encode_median_ms": baseline_metrics["encode_median_ms"],
            "baseline_decode_median_ms": baseline_metrics["decode_median_ms"],
            "prithvi_encode_median_ms": prithvi_metrics["encode_median_ms"],
            "prithvi_decode_median_ms": prithvi_metrics["decode_median_ms"],
            "tangent_encode_median_ms": tangent_metrics["encode_median_ms"],
            "tangent_decode_median_ms": tangent_metrics["decode_median_ms"],
            "weighted_tangent_encode_median_ms": weighted_metrics["encode_median_ms"],
            "weighted_tangent_decode_median_ms": weighted_metrics["decode_median_ms"],
            "baseline_max_vertex_error": baseline_metrics["max_vertex_error"],
            "prithvi_max_vertex_error": prithvi_metrics["max_vertex_error"],
            "tangent_max_vertex_error": tangent_metrics["max_vertex_error"],
            "weighted_tangent_max_vertex_error": weighted_metrics["max_vertex_error"],
            "baseline_rmse_vertex_distance": baseline_metrics["rmse_vertex_distance"],
            "prithvi_rmse_vertex_distance": prithvi_metrics["rmse_vertex_distance"],
            "tangent_rmse_vertex_distance": tangent_metrics["rmse_vertex_distance"],
            "weighted_tangent_rmse_vertex_distance": weighted_metrics["rmse_vertex_distance"],
            "baseline_topology_exact": baseline_metrics["topology_exact"],
            "prithvi_topology_exact": prithvi_metrics["topology_exact"],
            "tangent_topology_exact": tangent_metrics["topology_exact"],
            "weighted_tangent_topology_exact": weighted_metrics["topology_exact"],
            "tangent_predictive_vertices": tangent_metrics["predictive_vertices"],
            "weighted_tangent_predictive_vertices": weighted_metrics["predictive_vertices"],
            "tangent_residual_step": tangent_metrics["tangent_residual_step"],
            "weighted_tangent_residual_step": weighted_metrics["tangent_residual_step"],
            "draco_bytes": draco_metrics["bytes"],
            "draco_size_reduction_vs_baseline_pct": round(
                (1 - draco_metrics["bytes"] / baseline_metrics["bytes"]) * 100, 4
            ) if baseline_metrics["bytes"] else None,
            "draco_encode_median_ms": draco_metrics["encode_median_ms"],
            "draco_decode_median_ms": draco_metrics["decode_median_ms"],
            "draco_max_vertex_error": draco_metrics["max_vertex_error"],
            "draco_rmse_vertex_distance": draco_metrics["rmse_vertex_distance"],
            "draco_topology_equivalent": draco_metrics["topology_equivalent"],
            "draco_topology_exact_face_order": draco_metrics["topology_exact_face_order"],
            "draco_quantization_bits": draco_metrics["quantization_bits"],
            "quantized_positions_equal": positions_equal,
            "candidate_metrics": coder_metrics,
        }
        ordering_results.append(result)

    source = next(item for item in ordering_results if item["ordering"] == "source")
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    per_axis_half_step = (np.asarray(vertices.max(axis=0)) - np.asarray(vertices.min(axis=0))) / (
        2 * ((1 << bits) - 1)
    )
    theoretical_error_bound = float(np.linalg.norm(per_axis_half_step))
    reference_max_error = float(np.linalg.norm(reference_decoded[0] - vertices, axis=1).max())

    # A rate-first adaptive choice over the exact candidate bitstreams we tested.
    # Ties prefer simpler/faster methods and then source order.
    method_priority = {name: idx for idx, name in enumerate(CODEC_METHODS)}
    ordering_priority = {name: idx for idx, name in enumerate(ORDERINGS)}
    candidates = [
        (method, result["ordering"], result["candidate_metrics"][method])
        for result in ordering_results
        for method in CODEC_METHODS
    ]
    best_method, best_ordering, best_metrics = min(
        candidates,
        key=lambda item: (
            item[2]["bytes"], method_priority[item[0]], ordering_priority[item[1]]
        ),
    )
    adaptive_encode_sweep_ms = round(
        sum(item[2]["encode_median_ms"] for item in candidates), 4
    )

    row: dict[str, Any] = {
        "file": str(path), "name": path.name,
        "source_format": path.suffix.lower(), "source_bytes": len(original),
        "vertices": int(len(vertices)), "triangles": int(len(faces)),
        "position_bits": bits, "repeats": repeats,
        "gzip_lossless_bytes": len(gzip_bytes),
        "gzip_lossless_ratio_vs_source": round(len(original) / len(gzip_bytes), 6) if gzip_bytes else None,
        "gzip_encode_median_ms": round(gzip_seconds * 1000, 4),
        "simple_geometry_zlib_reference_bytes": len(reference_bytes),
        "simple_geometry_zlib_reference_encode_median_ms": round(reference_seconds * 1000, 4),
        "simple_geometry_zlib_reference_decode_median_ms": round(reference_decode_seconds * 1000, 4),
        "simple_reference_topology_exact": bool(np.array_equal(reference_decoded[1], faces)),
        "simple_reference_geometry_max_vertex_error": reference_max_error,
        "mo3d_size_reduction_vs_simple_reference_pct": round(
            (1 - source["baseline_bytes"] / len(reference_bytes)) * 100, 4
        ) if reference_bytes else None,
        "mo3d_lossy_geometry_bytes": source["baseline_bytes"],
        "mo3d_source_to_encoded_ratio": round(
            len(original) / source["baseline_bytes"], 6
        ) if source["baseline_bytes"] else None,
        "mo3d_size_saved_vs_source_pct": round(
            (1 - source["baseline_bytes"] / len(original)) * 100, 4
        ) if original else None,
        "mo3d_coordinate_coder": "absolute-fixed-width-zlib",
        "mo3d_encode_median_ms": source["baseline_encode_median_ms"],
        "mo3d_decode_median_ms": source["baseline_decode_median_ms"],
        "prithvi_bytes": source["prithvi_bytes"],
        "prithvi_size_reduction_vs_mo3d_baseline_pct": source["prithvi_size_reduction_vs_baseline_pct"],
        "prithvi_encode_median_ms": source["prithvi_encode_median_ms"],
        "prithvi_decode_median_ms": source["prithvi_decode_median_ms"],
        "prithvi_geometry_max_vertex_error": source["prithvi_max_vertex_error"],
        "prithvi_geometry_rmse_vertex_distance": source["prithvi_rmse_vertex_distance"],
        "prithvi_topology_exact": source["prithvi_topology_exact"],
        "prithvi_coordinate_coder": "prithvi-mesh-adjacency-residual-varint-zlib",
        "tangent_bytes": source["tangent_bytes"],
        "tangent_size_reduction_vs_baseline_pct": source["tangent_size_reduction_vs_baseline_pct"],
        "tangent_encode_median_ms": source["tangent_encode_median_ms"],
        "tangent_decode_median_ms": source["tangent_decode_median_ms"],
        "tangent_geometry_max_vertex_error": source["tangent_max_vertex_error"],
        "tangent_geometry_rmse_vertex_distance": source["tangent_rmse_vertex_distance"],
        "tangent_topology_exact": source["tangent_topology_exact"],
        "weighted_tangent_bytes": source["weighted_tangent_bytes"],
        "weighted_tangent_size_reduction_vs_baseline_pct": source["weighted_tangent_size_reduction_vs_baseline_pct"],
        "weighted_tangent_encode_median_ms": source["weighted_tangent_encode_median_ms"],
        "weighted_tangent_decode_median_ms": source["weighted_tangent_decode_median_ms"],
        "weighted_tangent_geometry_max_vertex_error": source["weighted_tangent_max_vertex_error"],
        "weighted_tangent_geometry_rmse_vertex_distance": source["weighted_tangent_rmse_vertex_distance"],
        "weighted_tangent_topology_exact": source["weighted_tangent_topology_exact"],
        "draco_bytes": source["draco_bytes"],
        "draco_size_reduction_vs_baseline_pct": source["draco_size_reduction_vs_baseline_pct"],
        "draco_encode_median_ms": source["draco_encode_median_ms"],
        "draco_decode_median_ms": source["draco_decode_median_ms"],
        "draco_geometry_max_vertex_error": source["draco_max_vertex_error"],
        "draco_geometry_rmse_vertex_distance": source["draco_rmse_vertex_distance"],
        "draco_topology_equivalent": source["draco_topology_equivalent"],
        "bbox_diagonal": diagonal,
        "max_error_bound_estimate": theoretical_error_bound,
        "topology_exact": source["baseline_topology_exact"],
        "attributes_preserved": ["triangle connectivity", "vertex positions (quantized or bounded tangent residuals)"],
        "attributes_dropped": ["normals", "UVs", "colors", "textures", "materials", "source-format metadata"],
        "fair_comparison_warning": (
            "Each method/order combination uses the same geometry/topology and position-bit setting. "
            "The tangent methods use a scalar residual step chosen to match the baseline quantizer's "
            "conservative Euclidean error bound; actual distortion is measured separately. Results are "
            "synthetic, geometry-only and lossy. Compare against Draco with matched attributes and distortion."
        ),
        "decoder_bytes_exact": bool(source["baseline_topology_exact"]),
        "prithvi_decoder_bytes_exact": bool(source["prithvi_topology_exact"]),
        "baseline_prithvi_quantized_positions_equal": source["quantized_positions_equal"],
        "best_candidate_method": best_method,
        "best_candidate_ordering": best_ordering,
        "best_candidate_bytes": best_metrics["bytes"],
        "best_candidate_max_vertex_error": best_metrics["max_vertex_error"],
        "best_candidate_size_reduction_vs_source_order_baseline_pct": round(
            (1 - best_metrics["bytes"] / source["baseline_bytes"]) * 100, 4
        ) if source["baseline_bytes"] else None,
        "adaptive_encode_sweep_estimate_ms": adaptive_encode_sweep_ms,
        "ordering_results": ordering_results,
        "header_version": 1,
    }
    # Flatten each candidate's scalar results into CSV columns while retaining
    # the nested JSON record for downstream plots and analyses.
    for result in ordering_results:
        ordering = result["ordering"]
        for method in CODEC_METHODS:
            for key, value in result["candidate_metrics"][method].items():
                if key not in {"ordering", "method"}:
                    row[f"{ordering}_{method}_{key}"] = value
        for key, value in result.items():
            if key not in {"ordering", "candidate_metrics"}:
                row[f"{ordering}_{key}"] = value
    return row


def benchmark_directory(input_dir: str | Path, output_json: str | Path, bits: int = 16, repeats: int = 3) -> dict[str, Any]:
    if not isinstance(bits, int) or not 8 <= bits <= 24:
        raise ValueError("bits must be from 8 through 24")
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    files = sorted(p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in MESH_EXTENSIONS)
    if not files:
        raise ValueError(f"No mesh files found in {input_dir}; supported extensions: {', '.join(sorted(MESH_EXTENSIONS))}")
    rows = []
    errors = []
    for path in files:
        try:
            rows.append(benchmark_file(path, bits=bits, repeats=repeats))
        except Exception as exc:
            errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})
    if not rows:
        raise RuntimeError("No files could be benchmarked; see input errors")
    report = {
        "project": "MiddleOut-3D",
        "report_version": 2,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__},
        "configuration": {"position_bits": bits, "repeats": repeats, "methods": list(CODEC_METHODS), "vertex_orderings": list(ORDERINGS), "external_baseline": "Google Draco via DracoPy, same nominal quantization_bits as the MO3D position_bits setting, compression_level=7", "timing_statistic": "median wall-clock time via perf_counter", "warmup": "not explicitly separated"},
        "results": rows, "errors": errors,
        "conclusion_policy": "This prototype is not considered better than LZ4 or Draco unless comparison uses equivalent data, attribute preservation, distortion constraints, and repeatable encode/decode measurements. Tangent methods target the baseline's conservative geometric error bound. Auto selection chooses the shortest observed candidate bitstream across all tested methods and orderings, at increased encoding cost.",
    }
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    csv_path = output_json.with_suffix(".csv")
    columns = sorted({key for row in rows for key in row if isinstance(row[key], (str, int, float, bool)) or row[key] is None})
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] if not isinstance(row[k], (list, dict)) else json.dumps(row[k]) for k in columns})
    return {"report": str(output_json), "csv": str(csv_path), "files_found": len(files), "files_benchmarked": len(rows), "errors": len(errors)}
