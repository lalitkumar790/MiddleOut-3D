"""Experimental quantized triangle-mesh codec for MiddleOut-3D.

MO3D v1 supports two coordinate coders:
- baseline: quantized absolute XYZ values, zlib-compressed.
- prithvi: a mesh-adjacency causal predictor followed by signed residual varints
  and zlib. "Prithvi" is a design analogy inspired by Atharvaveda 12.1
  (Prithvi Sukta), not a claim that the scripture describes a compression method.

Both are lossy in position and omit mesh attributes outside XYZ + triangle faces.
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
METHODS = ("baseline", "prithvi")


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
            raise CodecError("too many varints in stream")
        value = 0
        shift = 0
    if shift != 0 or len(out) != expected:
        raise CodecError(f"expected {expected} varints, got {len(out)}")
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


def _quantize(vertices: np.ndarray, bits: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mins = vertices.min(axis=0)
    maxs = vertices.max(axis=0)
    spans = maxs - mins
    levels = (1 << bits) - 1
    safe_spans = np.where(spans == 0.0, 1.0, spans)
    quantized = np.rint((vertices - mins) / safe_spans * levels).clip(0, levels).astype(np.int64)
    return quantized, mins, maxs


def _mesh_parents(faces: np.ndarray, vertex_count: int) -> np.ndarray:
    """Pick each vertex's greatest lower-index mesh neighbor as its causal parent.

    For every edge (u, v), the higher-index endpoint uses the lower endpoint as
    a possible predictor. The maximum eligible parent gives a deterministic
    choice that the decoder can recompute from the decoded face stream alone.
    A vertex with no earlier adjacent vertex has parent -1 and is coded absolute.
    """
    parents = np.full(vertex_count, -1, dtype=np.int64)
    for tri in faces:
        a, b, c = (int(x) for x in tri)
        for u, v in ((a, b), (b, c), (c, a)):
            if u == v:
                continue
            hi, lo = (u, v) if u > v else (v, u)
            if hi > lo and lo > parents[hi]:
                parents[hi] = lo
    return parents


def _encode_face_stream(faces: np.ndarray, level: int) -> bytes:
    face_delta_stream = bytearray()
    previous = 0
    for raw_index in faces.reshape(-1):
        current = int(raw_index)
        face_delta_stream.extend(_encode_varint(_zigzag_encode(current - previous)))
        previous = current
    return zlib.compress(bytes(face_delta_stream), level)


def _decode_face_stream(face_raw: bytes, vertex_count: int, face_count: int) -> np.ndarray:
    face_deltas = _decode_varints(face_raw, face_count * 3)
    indices: list[int] = []
    previous = 0
    for zigzag in face_deltas:
        current = previous + _zigzag_decode(zigzag)
        if current < 0 or current >= vertex_count:
            raise CodecError("decoded face index is out of range")
        indices.append(current)
        previous = current
    return np.asarray(indices, dtype=np.int64).reshape(face_count, 3)


def _encode_prithvi_coordinates(quantized: np.ndarray, faces: np.ndarray, level: int) -> bytes:
    """Encode quantized coordinate residuals against earlier adjacent vertices."""
    parents = _mesh_parents(faces, len(quantized))
    residual_stream = bytearray()
    for index, q in enumerate(quantized):
        parent = int(parents[index])
        prediction = quantized[parent] if parent >= 0 else np.zeros(3, dtype=np.int64)
        for residual in (q - prediction):
            residual_stream.extend(_encode_varint(_zigzag_encode(int(residual))))
    return zlib.compress(bytes(residual_stream), level)


def _decode_prithvi_coordinates(coord_raw: bytes, faces: np.ndarray, vertex_count: int, bits: int) -> np.ndarray:
    residuals = _decode_varints(coord_raw, vertex_count * 3)
    parents = _mesh_parents(faces, vertex_count)
    levels = (1 << bits) - 1
    quantized = np.zeros((vertex_count, 3), dtype=np.int64)
    cursor = 0
    for index in range(vertex_count):
        parent = int(parents[index])
        prediction = quantized[parent] if parent >= 0 else np.zeros(3, dtype=np.int64)
        reconstructed = []
        for axis in range(3):
            value = int(prediction[axis]) + _zigzag_decode(residuals[cursor])
            cursor += 1
            if value < 0 or value > levels:
                raise CodecError("decoded coordinate residual is outside quantization range")
            reconstructed.append(value)
        quantized[index] = reconstructed
    return quantized


def encode_mesh(vertices: Any, faces: Any, bits: int = 16, level: int = 6, method: str = "baseline") -> bytes:
    """Encode a triangle mesh as MO3D bytes.

    Args:
        vertices: N x 3 numeric coordinate array.
        faces: M x 3 triangle indices.
        bits: Per-axis position precision, 8–24 bits.
        level: zlib compression level, 0–9.
        method: "baseline" or "prithvi". Prithvi predicts each quantized vertex
            from its greatest lower-indexed adjacent vertex, coding signed
            coordinate residuals rather than absolute coordinates.

    Geometry is lossy because coordinates are quantized. Normals, UVs, colors,
    textures, material data and source-format metadata are omitted.
    """
    if not isinstance(bits, int) or isinstance(bits, bool) or not 8 <= bits <= 24:
        raise CodecError("bits must be an integer from 8 through 24")
    if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 9:
        raise CodecError("zlib level must be an integer from 0 through 9")
    if method not in METHODS:
        raise CodecError(f"method must be one of: {', '.join(METHODS)}")
    vertices, faces = _validate_mesh(vertices, faces)
    quantized, mins, maxs = _quantize(vertices, bits)
    if method == "prithvi":
        coord_stream = _encode_prithvi_coordinates(quantized, faces, level)
        coordinate_coder = "prithvi-mesh-adjacency-residual-varint-zlib"
    else:
        coord_dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
        coord_stream = zlib.compress(quantized.astype(coord_dtype).tobytes(order="C"), level)
        coordinate_coder = "absolute-fixed-width-zlib"
    face_stream = _encode_face_stream(faces, level)

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
        "coordinate_coder": coordinate_coder,
        "position_quantization": "uniform per axis, bounding-box normalized",
        "topology": "triangles, delta indices with zigzag varints, zlib",
        "method_note": "Prithvi is an engineering analogy inspired by Atharvaveda 12.1, not a claim of a compression algorithm in the text." if method == "prithvi" else "Baseline absolute-coordinate coder.",
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
    if not isinstance(bits, int) or isinstance(bits, bool) or not 8 <= bits <= 24:
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
    faces = _decode_face_stream(face_raw, vertex_count, face_count)
    levels = (1 << bits) - 1
    try:
        mins = np.asarray(header.get("bounds_min"), dtype=np.float64)
        maxs = np.asarray(header.get("bounds_max"), dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise CodecError("invalid bounding box metadata") from exc
    if mins.shape != (3,) or maxs.shape != (3,) or not np.isfinite(mins).all() or not np.isfinite(maxs).all() or np.any(maxs < mins):
        raise CodecError("invalid bounding box metadata")

    coder = header.get("coordinate_coder", "absolute-fixed-width-zlib")
    if coder == "absolute-fixed-width-zlib":
        dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
        expected_coord_bytes = vertex_count * 3 * dtype.itemsize
        if len(coord_raw) != expected_coord_bytes:
            raise CodecError("coordinate data length does not match vertex count")
        quantized = np.frombuffer(coord_raw, dtype=dtype).astype(np.int64).reshape(vertex_count, 3)
        if np.any(quantized > levels):
            raise CodecError("absolute coordinate is outside quantization range")
    elif coder == "prithvi-mesh-adjacency-residual-varint-zlib":
        quantized = _decode_prithvi_coordinates(coord_raw, faces, vertex_count, bits)
    else:
        raise CodecError(f"unsupported coordinate coder: {coder!r}")
    vertices = mins + (quantized.astype(np.float64) / levels) * (maxs - mins)
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


def encode_file(input_path: str | Path, output_path: str | Path, bits: int = 16, method: str = "baseline") -> dict[str, Any]:
    vertices, faces, _ = load_mesh(input_path)
    encoded = encode_mesh(vertices, faces, bits=bits, method=method)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    return {"input": str(input_path), "output": str(output_path), "input_bytes": Path(input_path).stat().st_size,
            "output_bytes": len(encoded), "ratio": Path(input_path).stat().st_size / len(encoded),
            "position_bits": bits, "method": method, "vertices": len(vertices), "faces": len(faces)}


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
            "position_bits": header["position_bits"], "method": header.get("coordinate_coder", "absolute-fixed-width-zlib")}
