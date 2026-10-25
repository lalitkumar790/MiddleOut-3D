"""Experimental quantized triangle-mesh codec for MiddleOut-3D.

Prototype format MO3D v1 stores quantized XYZ coordinates and delta/varint-
encoded triangle indices, each compressed with zlib. It is intentionally
lossy in vertex positions and currently drops normals, UVs, colors and materials.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np

MAGIC = b"MO3D\x01"
MAX_HEADER_BYTES = 1_000_000
MAX_ITEMS = 100_000_000


class CodecError(ValueError):
    """Invalid or unsupported MO3D bitstream or mesh data."""


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint only supports unsigned integers")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _decode_varints(data: bytes, expected: int) -> list[int]:
    out: list[int] = []
    value = 0
    shift = 0
    for byte in data:
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
            if shift > 63:
                raise CodecError("invalid or oversized varint")
            continue
        out.append(value)
        if len(out) > expected:
            raise CodecError("too many face indices")
        value = 0
        shift = 0
    if shift != 0 or len(out) != expected:
        raise CodecError(f"expected {expected} face indices, got {len(out)}")
    return out


def _zigzag_encode(value: int) -> int:
    return value * 2 if value >= 0 else (-value * 2) - 1


def _zigzag_decode(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _validate_mesh(vertices: Any, faces: Any) -> tuple[np.ndarray, np.ndarray]:
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or vertices.shape[0] < 1:
        raise CodecError("vertices must be a non-empty N x 3 array")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise CodecError("faces must be an M x 3 triangle-index array")
    if faces.size == 0:
        raise CodecError("mesh must contain at least one triangle")
    if not np.isfinite(vertices).all():
        raise CodecError("vertices contain NaN or infinity")
    if not np.issubdtype(faces.dtype, np.integer):
        if not np.all(np.equal(faces, np.floor(faces))):
            raise CodecError("face indices must be integers")
    faces = faces.astype(np.int64, copy=False)
    if faces.min() < 0 or faces.max() >= len(vertices):
        raise CodecError("face index is outside the vertex array")
    if len(vertices) > MAX_ITEMS or len(faces) > MAX_ITEMS:
        raise CodecError("mesh exceeds the prototype's safety limit")
    return vertices, faces


def encode_mesh(vertices: Any, faces: Any, bits: int = 16, level: int = 6) -> bytes:
    """Encode triangle geometry to MO3D bytes using lossy position quantization.

    Only vertex positions and triangle connectivity are stored. Attribute data
    such as normals, UVs, colors, textures and material definitions are omitted.
    """
    if not isinstance(bits, int) or not 8 <= bits <= 24:
        raise CodecError("bits must be an integer from 8 through 24")
    if not isinstance(level, int) or not 0 <= level <= 9:
        raise CodecError("zlib level must be an integer from 0 through 9")
    vertices, faces = _validate_mesh(vertices, faces)
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    spans = maxs - mins
    levels = (1 << bits) - 1
    safe_spans = np.where(spans == 0.0, 1.0, spans)
    quantized = np.rint((vertices - mins) / safe_spans * levels).clip(0, levels).astype(np.uint32)
    coord_dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
    coord_stream = zlib.compress(quantized.astype(coord_dtype).tobytes(order="C"), level)

    face_delta_stream = bytearray()
    previous = 0
    for raw_index in faces.reshape(-1):
        current = int(raw_index)
        face_delta_stream.extend(_encode_varint(_zigzag_encode(current - previous)))
        previous = current
    face_stream = zlib.compress(bytes(face_delta_stream), level)

    header = {
        "format": "MO3D",
        "version": 1,
        "position_bits": bits,
        "vertex_count": int(len(vertices)),
        "face_count": int(len(faces)),
        "bounds_min": mins.tolist(),
        "bounds_max": maxs.tolist(),
        "coordinate_stream_bytes": len(coord_stream),
        "face_stream_bytes": len(face_stream),
        "position_quantization": "uniform per axis, bounding-box normalized",
        "topology": "triangles, delta indices with zigzag varints, zlib",
    }
    header_bytes = json.dumps(header, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes + coord_stream + face_stream


def decode_mesh(payload: bytes) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Decode MO3D bytes; returns reconstructed vertices, faces and metadata."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")
    payload = bytes(payload)
    if len(payload) < len(MAGIC) + 4 or not payload.startswith(MAGIC):
        raise CodecError("not a supported MO3D bitstream")
    header_len = struct.unpack(">I", payload[len(MAGIC):len(MAGIC) + 4])[0]
    start = len(MAGIC) + 4
    if header_len < 2 or header_len > MAX_HEADER_BYTES or start + header_len > len(payload):
        raise CodecError("invalid metadata header length")
    try:
        header = json.loads(payload[start:start + header_len].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodecError("invalid metadata header") from exc
    if not isinstance(header, dict) or header.get("format") != "MO3D" or header.get("version") != 1:
        raise CodecError("unsupported MO3D format version")
    bits = header.get("position_bits")
    vertex_count = header.get("vertex_count")
    face_count = header.get("face_count")
    coord_len = header.get("coordinate_stream_bytes")
    face_len = header.get("face_stream_bytes")
    if not isinstance(bits, int) or not 8 <= bits <= 24:
        raise CodecError("invalid position precision")
    for value, name in ((vertex_count, "vertex count"), (face_count, "face count"), (coord_len, "coordinate stream length"), (face_len, "face stream length")):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > MAX_ITEMS * 16:
            raise CodecError(f"invalid {name}")
    if vertex_count < 1 or face_count < 1:
        raise CodecError("empty meshes are not supported")
    if vertex_count > MAX_ITEMS or face_count > MAX_ITEMS:
        raise CodecError("mesh exceeds the prototype's safety limit")
    pos = start + header_len
    if pos + coord_len + face_len != len(payload):
        raise CodecError("truncated stream or unexpected trailing bytes")
    coord_stream = payload[pos:pos + coord_len]
    face_stream = payload[pos + coord_len:]
    try:
        coord_raw = zlib.decompress(coord_stream)
        face_raw = zlib.decompress(face_stream)
    except zlib.error as exc:
        raise CodecError("could not decompress geometry stream") from exc
    dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
    expected_coord_bytes = vertex_count * 3 * dtype.itemsize
    if len(coord_raw) != expected_coord_bytes:
        raise CodecError("coordinate data length does not match vertex count")
    q = np.frombuffer(coord_raw, dtype=dtype).astype(np.float64).reshape(vertex_count, 3)
    levels = (1 << bits) - 1
    try:
        mins = np.asarray(header.get("bounds_min"), dtype=np.float64)
        maxs = np.asarray(header.get("bounds_max"), dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise CodecError("invalid bounding box metadata") from exc
    if mins.shape != (3,) or maxs.shape != (3,) or not np.isfinite(mins).all() or not np.isfinite(maxs).all() or np.any(maxs < mins):
        raise CodecError("invalid bounding box metadata")
    vertices = mins + (q / levels) * (maxs - mins)
    face_deltas = _decode_varints(face_raw, face_count * 3)
    indices = []
    previous = 0
    for zigzag in face_deltas:
        current = previous + _zigzag_decode(zigzag)
        if current < 0 or current >= vertex_count:
            raise CodecError("decoded face index is out of range")
        indices.append(current)
        previous = current
    faces = np.asarray(indices, dtype=np.int64).reshape(face_count, 3)
    return vertices, faces, header


def load_mesh(path: str | Path) -> tuple[np.ndarray, np.ndarray, Any]:
    """Load a triangle mesh via trimesh without merging/reordering vertices."""
    try:
        import trimesh
    except ImportError as exc:
        raise RuntimeError("Install project dependencies with: python -m pip install -r requirements.txt") from exc
    loaded = trimesh.load(str(path), force="mesh", process=False)
    vertices, faces = _validate_mesh(loaded.vertices, loaded.faces)
    return vertices, faces, loaded


def encode_file(input_path: str | Path, output_path: str | Path, bits: int = 16) -> dict[str, Any]:
    vertices, faces, _ = load_mesh(input_path)
    encoded = encode_mesh(vertices, faces, bits=bits)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    return {"input": str(input_path), "output": str(output_path), "input_bytes": Path(input_path).stat().st_size,
            "output_bytes": len(encoded), "ratio": Path(input_path).stat().st_size / len(encoded),
            "position_bits": bits, "vertices": len(vertices), "faces": len(faces)}


def decode_file(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    try:
        import trimesh
    except ImportError as exc:
        raise RuntimeError("Install project dependencies with: python -m pip install -r requirements.txt") from exc
    data = Path(input_path).read_bytes()
    vertices, faces, header = decode_mesh(data)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_type = output_path.suffix.lower().lstrip(".")
    if file_type not in {"obj", "ply", "stl", "off"}:
        raise CodecError("output extension must be .obj, .ply, .stl or .off")
    mesh.export(str(output_path), file_type=file_type)
    return {"input": str(input_path), "output": str(output_path), "input_bytes": len(data),
            "output_bytes": output_path.stat().st_size, "vertices": header["vertex_count"], "faces": header["face_count"],
            "position_bits": header["position_bits"]}
