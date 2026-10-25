"""Reproducible first-pass benchmark for MiddleOut-3D."""
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

from .codec import decode_mesh, encode_mesh, load_mesh

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


def benchmark_file(path: Path, bits: int = 16, repeats: int = 3) -> dict[str, Any]:
    original = path.read_bytes()
    vertices, faces, _ = load_mesh(path)
    gzip_bytes, gzip_seconds = _timed(lambda: gzip.compress(original, compresslevel=6, mtime=0), repeats)
    reference_bytes, reference_seconds = _timed(lambda: _simple_geometry_zlib_reference(vertices, faces, bits), repeats)
    reference_decoded, reference_decode_seconds = _timed(lambda: _decode_simple_geometry_zlib_reference(reference_bytes), repeats)
    mo3d_bytes, encode_seconds = _timed(lambda: encode_mesh(vertices, faces, bits=bits, method="baseline"), repeats)
    decoded, decode_seconds = _timed(lambda: decode_mesh(mo3d_bytes), repeats)
    decoded_vertices, decoded_faces, meta = decoded
    prithvi_bytes, prithvi_encode_seconds = _timed(lambda: encode_mesh(vertices, faces, bits=bits, method="prithvi"), repeats)
    prithvi_decoded, prithvi_decode_seconds = _timed(lambda: decode_mesh(prithvi_bytes), repeats)
    prithvi_vertices, prithvi_faces, prithvi_meta = prithvi_decoded
    errors = np.linalg.norm(decoded_vertices - vertices, axis=1)
    prithvi_errors = np.linalg.norm(prithvi_vertices - vertices, axis=1)
    topology_equal = bool(np.array_equal(decoded_faces, faces))
    prithvi_topology_equal = bool(np.array_equal(prithvi_faces, faces))
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    per_axis_half_step = (np.asarray(vertices.max(axis=0)) - np.asarray(vertices.min(axis=0))) / (2 * ((1 << bits) - 1))
    theoretical_error_bound = float(np.linalg.norm(per_axis_half_step))
    mo3d_size = len(mo3d_bytes)
    return {
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
        "simple_reference_geometry_max_vertex_error": float(np.linalg.norm(reference_decoded[0] - vertices, axis=1).max()),
        "mo3d_size_reduction_vs_simple_reference_pct": round((1 - mo3d_size / len(reference_bytes)) * 100, 4) if reference_bytes else None,
        "mo3d_lossy_geometry_bytes": mo3d_size,
        "mo3d_source_to_encoded_ratio": round(len(original) / mo3d_size, 6) if mo3d_size else None,
        "mo3d_size_saved_vs_source_pct": round((1 - mo3d_size / len(original)) * 100, 4) if original else None,
        "mo3d_coordinate_coder": meta.get("coordinate_coder", "absolute-fixed-width-zlib"),
        "mo3d_encode_median_ms": round(encode_seconds * 1000, 4),
        "mo3d_decode_median_ms": round(decode_seconds * 1000, 4),
        "prithvi_bytes": len(prithvi_bytes),
        "prithvi_size_reduction_vs_mo3d_baseline_pct": round((1 - len(prithvi_bytes) / len(mo3d_bytes)) * 100, 4) if mo3d_bytes else None,
        "prithvi_encode_median_ms": round(prithvi_encode_seconds * 1000, 4),
        "prithvi_decode_median_ms": round(prithvi_decode_seconds * 1000, 4),
        "prithvi_geometry_max_vertex_error": float(prithvi_errors.max()) if prithvi_errors.size else 0.0,
        "prithvi_geometry_rmse_vertex_distance": float(np.sqrt(np.mean(prithvi_errors ** 2))) if prithvi_errors.size else 0.0,
        "prithvi_topology_exact": prithvi_topology_equal,
        "prithvi_coordinate_coder": prithvi_meta.get("coordinate_coder", ""),
        "geometry_max_vertex_error": float(errors.max()) if errors.size else 0.0,
        "geometry_rmse_vertex_distance": float(np.sqrt(np.mean(errors ** 2))) if errors.size else 0.0,
        "bbox_diagonal": diagonal,
        "max_error_bound_estimate": theoretical_error_bound,
        "topology_exact": topology_equal,
        "attributes_preserved": ["triangle connectivity", "vertex positions (quantized)"],
        "attributes_dropped": ["normals", "UVs", "colors", "textures", "materials", "source-format metadata"],
        "fair_comparison_warning": "The simple geometry zlib reference and MO3D both encode quantized positions at the same configured precision and triangle connectivity, omitting the same attributes, so their size comparison is a useful narrow ablation. Both are lossy relative to source geometry. The source-file ratio is not a fair codec comparison because source files may include formatting and attributes. gzip is lossless on the exact source bytes. Compare against Draco with matched attributes and distortion settings before broader claims.",
        "decoder_bytes_exact": bool(len(decoded_vertices) == len(vertices) and topology_equal),
        "prithvi_decoder_bytes_exact": bool(len(prithvi_vertices) == len(vertices) and prithvi_topology_equal),
        "baseline_prithvi_quantized_positions_equal": bool(np.array_equal(prithvi_vertices, decoded_vertices)),
        "header_version": meta["version"],
    }


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
        "report_version": 1,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__},
        "configuration": {"position_bits": bits, "repeats": repeats, "timing_statistic": "median wall-clock time via perf_counter", "warmup": "not explicitly separated"},
        "results": rows, "errors": errors,
        "conclusion_policy": "This prototype is not considered better than LZ4 or Draco unless comparison uses equivalent data, attribute preservation, distortion constraints, and repeatable encode/decode measurements.",
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
