"""Experimental quantized triangle-mesh codec for MiddleOut-3D.

MO3D v1 stores baseline absolute quantized XYZ values; MO3D v2 adds a
Prithvi mesh-adjacency residual coder; MO3D v3 experiments with a
parallelogram predictor and local tangent-space residuals. "Prithvi" is a design analogy inspired
by Atharvaveda 12.1 (Prithvi Sukta), not a claim that the scripture describes
a compression method.

Both are lossy in position and omit mesh attributes outside XYZ + triangle faces.
"""
from __future__ import annotations

import json
import math
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np

MAGIC_V1 = b"MO3D\x01"
MAGIC_V2 = b"MO3D\x02"
MAGIC_V3 = b"MO3D\x03"
MAGIC_V4 = b"MO3D\x04"
MAGIC_V5 = b"MO3D\x05"
MAGIC_V6 = b"MO3D\x06"
MAGIC_V7 = b"MO3D\x07"
MAGIC = MAGIC_V1  # backward-compatible name for the original v1 signature
MAX_HEADER_BYTES = 1_000_000
MAX_ITEMS = 100_000_000
CODEC_METHODS = ("baseline", "prithvi", "tangent", "weighted_tangent", "normal_fine_tangent", "chandas_tangent", "chandas_adaptive_tangent")
METHODS = CODEC_METHODS + ("auto",)


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


CHANDAS_BLOCK_SIZE = 64


def _read_varint(data: bytes, cursor: int) -> tuple[int, int]:
    """Read one unsigned varint and return (value, new_cursor)."""
    value = 0
    shift = 0
    while cursor < len(data):
        byte = data[cursor]
        cursor += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
            if shift > 63:
                raise CodecError("invalid or oversized varint")
            continue
        return value, cursor
    raise CodecError("truncated varint")


def _combination_rank_colex(positions: list[int]) -> int:
    """Rank a sorted subset with the combinatorial number system."""
    return sum(math.comb(position, index + 1) for index, position in enumerate(positions))


def _combination_unrank_colex(rank: int, n: int, k: int) -> list[int]:
    """Inverse of _combination_rank_colex for 0 <= rank < C(n, k)."""
    if k < 0 or k > n or rank < 0 or rank >= math.comb(n, k):
        raise CodecError("invalid enumerative subset rank")
    positions = [0] * k
    upper = n
    for order in range(k, 0, -1):
        low, high = order - 1, upper - 1
        best = order - 1
        while low <= high:
            mid = (low + high) // 2
            if math.comb(mid, order) <= rank:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        positions[order - 1] = best
        rank -= math.comb(best, order)
        upper = best
    if rank != 0:
        raise CodecError("invalid enumerative subset rank")
    return positions


def _encode_chandas_sparse_signed(values: list[int]) -> bytes:
    """Encode sparse signed residuals by enumerating non-zero positions per block.

    Inspiration: Pingala's chandas procedures for enumerating, counting and
    recovering laghu/guru patterns (often described via prastara, nashta and
    uddishta). This is a modern adaptation: rank the subset of non-zero slots
    in each fixed-length block, then store only the non-zero signed magnitudes.
    The scripture/history is not claimed to contain this codec.
    """
    out = bytearray(b"CHS1")
    out.extend(_encode_varint(len(values)))
    for start in range(0, len(values), CHANDAS_BLOCK_SIZE):
        block = values[start:start + CHANDAS_BLOCK_SIZE]
        positions = [idx for idx, value in enumerate(block) if value != 0]
        nonzero_count = len(positions)
        out.extend(_encode_varint(nonzero_count))
        pattern_count = math.comb(len(block), nonzero_count)
        rank = _combination_rank_colex(positions)
        rank_bits = (pattern_count - 1).bit_length()
        rank_bytes = (rank_bits + 7) // 8
        if rank_bytes:
            out.extend(rank.to_bytes(rank_bytes, "big"))
        for position in positions:
            out.extend(_encode_varint(_zigzag_encode(int(block[position]))))
    return bytes(out)


def _decode_chandas_sparse_signed(data: bytes, expected_count: int) -> list[int]:
    if not data.startswith(b"CHS1"):
        raise CodecError("invalid Chandas sparse-residual signature")
    cursor = 4
    count, cursor = _read_varint(data, cursor)
    if count != expected_count:
        raise CodecError("Chandas residual count does not match the mesh topology")
    out: list[int] = []
    while len(out) < expected_count:
        block_len = min(CHANDAS_BLOCK_SIZE, expected_count - len(out))
        nonzero_count, cursor = _read_varint(data, cursor)
        if nonzero_count > block_len:
            raise CodecError("Chandas non-zero count exceeds block length")
        pattern_count = math.comb(block_len, nonzero_count)
        rank_bits = (pattern_count - 1).bit_length()
        rank_bytes = (rank_bits + 7) // 8
        if cursor + rank_bytes > len(data):
            raise CodecError("truncated Chandas subset rank")
        rank = int.from_bytes(data[cursor:cursor + rank_bytes], "big") if rank_bytes else 0
        cursor += rank_bytes
        if rank >= pattern_count:
            raise CodecError("Chandas subset rank is outside its range")
        positions = _combination_unrank_colex(rank, block_len, nonzero_count)
        block = [0] * block_len
        for position in positions:
            value, cursor = _read_varint(data, cursor)
            block[position] = _zigzag_decode(value)
        out.extend(block)
    if cursor != len(data):
        raise CodecError("unexpected trailing bytes in Chandas sparse residuals")
    return out


def _encode_chandas_sparse_block(values: list[int]) -> bytes:
    """Encode one fixed-length block by ranking its non-zero positions."""
    positions = [index for index, value in enumerate(values) if value != 0]
    count = len(positions)
    out = bytearray(_encode_varint(count))
    possible_patterns = math.comb(len(values), count)
    rank = _combination_rank_colex(positions)
    rank_bytes = ((possible_patterns - 1).bit_length() + 7) // 8
    if rank_bytes:
        out.extend(rank.to_bytes(rank_bytes, "big"))
    for position in positions:
        out.extend(_encode_varint(_zigzag_encode(int(values[position]))))
    return bytes(out)


def _decode_chandas_sparse_block(data: bytes, cursor: int, block_len: int) -> tuple[list[int], int]:
    """Decode one ranked non-zero-position block; return values and new cursor."""
    count, cursor = _read_varint(data, cursor)
    if count > block_len:
        raise CodecError("Chandas non-zero count exceeds block length")
    possible_patterns = math.comb(block_len, count)
    rank_bytes = ((possible_patterns - 1).bit_length() + 7) // 8
    if cursor + rank_bytes > len(data):
        raise CodecError("truncated Chandas subset rank")
    rank = int.from_bytes(data[cursor:cursor + rank_bytes], "big") if rank_bytes else 0
    cursor += rank_bytes
    if rank >= possible_patterns:
        raise CodecError("Chandas subset rank is outside its range")
    positions = _combination_unrank_colex(rank, block_len, count)
    block = [0] * block_len
    for position in positions:
        value, cursor = _read_varint(data, cursor)
        block[position] = _zigzag_decode(value)
    return block, cursor


def _encode_chandas_adaptive_residuals(values: list[int]) -> bytes:
    """Choose raw varints or sparse enumerative coding independently per block."""
    out = bytearray()
    for start in range(0, len(values), CHANDAS_BLOCK_SIZE):
        block = values[start:start + CHANDAS_BLOCK_SIZE]
        direct = bytearray()
        for value in block:
            direct.extend(_encode_varint(_zigzag_encode(int(value))))
        sparse = _encode_chandas_sparse_block(block)
        if len(sparse) < len(direct):
            out.append(1)
            out.extend(sparse)
        else:
            out.append(0)
            out.extend(direct)
    return bytes(out)


def _decode_chandas_adaptive_residuals(
    data: bytes, cursor: int, expected_count: int
) -> tuple[list[int], int]:
    """Decode a mixed stream of direct-varint and enumeratively coded blocks."""
    out: list[int] = []
    while len(out) < expected_count:
        block_len = min(CHANDAS_BLOCK_SIZE, expected_count - len(out))
        if cursor >= len(data):
            raise CodecError("truncated Chandas adaptive block stream")
        mode = data[cursor]
        cursor += 1
        if mode == 0:
            block = []
            for _ in range(block_len):
                value, cursor = _read_varint(data, cursor)
                block.append(_zigzag_decode(value))
        elif mode == 1:
            block, cursor = _decode_chandas_sparse_block(data, cursor, block_len)
        else:
            raise CodecError("unknown Chandas block coding mode")
        out.extend(block)
    return out, cursor


def _encode_chandas_adaptive_stream(seed_values: list[int], residual_values: list[int]) -> bytes:
    """Separate absolute seeds from residuals and use a locally adaptive block coder."""
    if len(seed_values) % 3:
        raise CodecError("seed coordinate stream must contain complete XYZ triples")
    out = bytearray(b"CHS2")
    out.extend(_encode_varint(len(seed_values) // 3))
    for value in seed_values:
        out.extend(_encode_varint(int(value)))
    out.extend(_encode_varint(len(residual_values)))
    out.extend(_encode_chandas_adaptive_residuals(residual_values))
    return bytes(out)


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


ORDERINGS = ("source", "bfs", "morton", "predictive")
FACE_CODING_OPTIONS = ("source", "rotate", "bfs")
FACE_ORDERINGS = (*FACE_CODING_OPTIONS, "auto")
# The auto selector compares complete payloads for source, rotation-only, and BFS.
AUTO_FACE_ORDERINGS = ("auto",)
# Predictive cost-guided traversal remains available experimentally, but the first
# benchmark found it consistently larger and much slower than source/BFS. Keep
# the user-facing rate-first auto search on the three proven orderings until a
# better predictive objective demonstrates a win.
AUTO_ORDERINGS = ("source", "bfs", "morton")


def _morton_spread_21(values: np.ndarray) -> np.ndarray:
    """Spread 21 input bits into every third bit of a 64-bit Morton code."""
    x = values.astype(np.uint64, copy=False) & np.uint64(0x1FFFFF)
    x = (x | (x << np.uint64(32))) & np.uint64(0x1F00000000FFFF)
    x = (x | (x << np.uint64(16))) & np.uint64(0x1F0000FF0000FF)
    x = (x | (x << np.uint64(8))) & np.uint64(0x100F00F00F00F00F)
    x = (x | (x << np.uint64(4))) & np.uint64(0x10C30C30C30C30C3)
    x = (x | (x << np.uint64(2))) & np.uint64(0x1249249249249249)
    return x


def _predictive_vertex_order(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Order vertices by an inexpensive estimate of causal residual-varint cost.

    This O((V+E) log V) frontier traversal replaces repeated evaluation of every
    candidate stencil. Once a vertex is visited, each unseen adjacent vertex's
    priority is updated using its quantized coordinate residual from that newly
    visited vertex. Because this is its latest visited neighbor, it will be the
    Prithvi parent under this traversal. The heuristic estimates residual cost;
    it does not promise the smallest complete mesh bitstream.
    """
    import heapq

    count = len(vertices)
    adjacency = [set() for _ in range(count)]
    for tri in faces:
        a, b, c = (int(x) for x in tri)
        for u, v in ((a, b), (b, c), (c, a)):
            if u != v:
                adjacency[u].add(v)
                adjacency[v].add(u)

    # Fixed 16-bit proxy so the ordering is independent of selected coder.
    quantized, _, _ = _quantize(vertices, 16)

    def estimated_residual_cost(target: int, parent: int) -> int:
        delta = quantized[target] - quantized[parent]
        return sum(len(_encode_varint(_zigzag_encode(int(value)))) for value in delta)

    visited = np.zeros(count, dtype=bool)
    versions = np.zeros(count, dtype=np.int64)
    order: list[int] = []
    heap: list[tuple[int, int, int]] = []

    def visit(vertex: int) -> None:
        if visited[vertex]:
            return
        visited[vertex] = True
        order.append(vertex)
        for neighbor in adjacency[vertex]:
            if visited[neighbor]:
                continue
            versions[neighbor] += 1
            cost = estimated_residual_cost(neighbor, vertex)
            heapq.heappush(heap, (cost, neighbor, int(versions[neighbor])))

    seed_face = None
    seed_key = None
    for face_index, tri in enumerate(faces):
        a, b, c = (int(x) for x in tri)
        area2 = float(np.linalg.norm(np.cross(vertices[b] - vertices[a], vertices[c] - vertices[a])))
        key = (area2, -face_index)
        if seed_key is None or key > seed_key:
            seed_key, seed_face = key, (a, b, c)
    if seed_face is not None:
        for vertex in seed_face:
            visit(vertex)

    while len(order) < count:
        while heap:
            _, vertex, version = heapq.heappop(heap)
            if visited[vertex] or version != int(versions[vertex]):
                continue
            visit(vertex)
            break
        else:
            # Start a disconnected component deterministically. Vertices unused
            # by any triangle are handled after all remaining face components.
            seed = None
            seed_key = None
            for face_index, tri in enumerate(faces):
                missing = [int(v) for v in tri if not visited[int(v)]]
                if not missing:
                    continue
                a, b, c = (int(x) for x in tri)
                area2 = float(np.linalg.norm(np.cross(vertices[b] - vertices[a], vertices[c] - vertices[a])))
                key = (len(missing), area2, -face_index)
                if seed_key is None or key > seed_key:
                    seed_key, seed = key, missing
            if seed:
                visit(min(seed))
            else:
                visit(int(np.flatnonzero(~visited)[0]))

    return np.asarray(order, dtype=np.int64)

def vertex_order_for_mesh(vertices: Any, faces: Any, ordering: str = "source") -> np.ndarray:
    """Return new-index -> original-index vertex permutation."""
    vertices, faces = _validate_mesh(vertices, faces)
    if ordering not in ORDERINGS:
        raise CodecError(f"ordering must be one of: {', '.join(ORDERINGS)}")
    count = len(vertices)
    if ordering == "source":
        return np.arange(count, dtype=np.int64)
    if ordering == "predictive":
        return _predictive_vertex_order(vertices, faces)
    if ordering == "morton":
        mins = vertices.min(axis=0)
        spans = vertices.max(axis=0) - mins
        safe_spans = np.where(spans == 0.0, 1.0, spans)
        max_grid = (1 << 21) - 1
        grid = np.rint((vertices - mins) / safe_spans * max_grid).clip(0, max_grid).astype(np.uint64)
        codes = _morton_spread_21(grid[:, 0]) | (_morton_spread_21(grid[:, 1]) << np.uint64(1)) | (_morton_spread_21(grid[:, 2]) << np.uint64(2))
        return np.lexsort((np.arange(count, dtype=np.int64), codes)).astype(np.int64)

    # Deterministic breadth-first traversal, one sorted-neighbor queue per connected component.
    adjacency = [set() for _ in range(count)]
    for tri in faces:
        a, b, c = (int(x) for x in tri)
        for u, v in ((a, b), (b, c), (c, a)):
            if u != v:
                adjacency[u].add(v)
                adjacency[v].add(u)
    from collections import deque
    visited = np.zeros(count, dtype=bool)
    order = []
    for root in range(count):
        if visited[root]:
            continue
        visited[root] = True
        queue = deque([root])
        while queue:
            vertex = queue.popleft()
            order.append(vertex)
            for neighbor in sorted(adjacency[vertex]):
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)
    return np.asarray(order, dtype=np.int64)


def reorder_mesh(vertices: Any, faces: Any, ordering: str = "source") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return reordered vertices, remapped faces, and new-index -> old-index map."""
    vertices, faces = _validate_mesh(vertices, faces)
    order = vertex_order_for_mesh(vertices, faces, ordering)
    inverse = np.empty_like(order)
    inverse[order] = np.arange(len(order), dtype=np.int64)
    return vertices[order], inverse[faces], order


def _mesh_parents(faces: np.ndarray, vertex_count: int) -> np.ndarray:
    """Pick each vertex's greatest lower-index mesh neighbor as its causal parent.

    The implementation vectorizes edge extraction while keeping the parent
    selection deterministic. For every undirected edge, the higher-index
    endpoint can use the lower endpoint as a predictor. A vertex with no
    earlier adjacent vertex has parent -1 and is coded absolute.
    """
    parents = np.full(vertex_count, -1, dtype=np.int64)
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]), axis=0)
    lo = np.minimum(edges[:, 0], edges[:, 1])
    hi = np.maximum(edges[:, 0], edges[:, 1])
    valid = hi > lo
    np.maximum.at(parents, hi[valid], lo[valid])
    return parents


def _mesh_parallelogram_candidates(faces: np.ndarray, vertex_count: int) -> list[list[tuple[int, int, int]]]:
    """Return causal parallelogram stencils per target vertex.

    If two triangles share edge (u, v) and their opposite vertices are target t
    and earlier vertex d, the classic parallelogram predictor is Q[u]+Q[v]-Q[d].
    A stencil is valid only when every predictor vertex has index < t, allowing
    the decoder to reproduce it without side information. Boundary edges have
    no opposite pair and therefore yield no stencil.
    """
    edge_opposites: dict[tuple[int, int], list[int]] = {}
    for tri in faces:
        a, b, c = (int(x) for x in tri)
        for u, v, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            if u == v or opposite in (u, v):
                continue
            edge = (u, v) if u < v else (v, u)
            edge_opposites.setdefault(edge, []).append(opposite)

    candidates: list[list[tuple[int, int, int]]] = [[] for _ in range(vertex_count)]
    for (u, v), raw_opposites in edge_opposites.items():
        opposites = sorted(set(raw_opposites))
        for target in opposites:
            if u >= target or v >= target:
                continue
            for other in opposites:
                if other == target or other >= target:
                    continue
                candidates[target].append((u, v, other))
    # Non-manifold input can create duplicate stencils; keep output deterministic.
    return [sorted(set(stencils)) for stencils in candidates]


def _predict_parallelogram(
    quantized: np.ndarray, candidates: list[list[tuple[int, int, int]]], index: int, fallback_parent: int
) -> np.ndarray:
    """Average every available prior-only parallelogram prediction."""
    stencils = candidates[index]
    if stencils:
        predictions = np.asarray(
            [quantized[u] + quantized[v] - quantized[opposite] for u, v, opposite in stencils],
            dtype=np.int64,
        )
        # np.rint gives deterministic nearest-even integer rounding in encoder/decoder.
        return np.rint(predictions.mean(axis=0)).astype(np.int64)
    if fallback_parent >= 0:
        return quantized[fallback_parent].astype(np.int64, copy=False)
    return np.zeros(3, dtype=np.int64)


def _encode_parallelogram_coordinates(quantized: np.ndarray, faces: np.ndarray, level: int) -> bytes:
    """Encode residuals from a multi-parallelogram predictor, then zlib."""
    fallback_parents = _mesh_parents(faces, len(quantized))
    candidates = _mesh_parallelogram_candidates(faces, len(quantized))
    residual_stream = bytearray()
    for index, target in enumerate(quantized):
        prediction = _predict_parallelogram(quantized, candidates, index, int(fallback_parents[index]))
        for residual in target - prediction:
            residual_stream.extend(_encode_varint(_zigzag_encode(int(residual))))
    return zlib.compress(bytes(residual_stream), level)


def _decode_parallelogram_coordinates(
    coord_raw: bytes, faces: np.ndarray, vertex_count: int, bits: int
) -> np.ndarray:
    residuals = _decode_varints(coord_raw, vertex_count * 3)
    fallback_parents = _mesh_parents(faces, vertex_count)
    candidates = _mesh_parallelogram_candidates(faces, vertex_count)
    levels = (1 << bits) - 1
    quantized = np.zeros((vertex_count, 3), dtype=np.int64)
    cursor = 0
    for index in range(vertex_count):
        prediction = _predict_parallelogram(quantized, candidates, index, int(fallback_parents[index]))
        reconstructed = prediction.copy()
        for axis in range(3):
            reconstructed[axis] += _zigzag_decode(residuals[cursor])
            cursor += 1
        if np.any(reconstructed < 0) or np.any(reconstructed > levels):
            raise CodecError("decoded parallelogram residual is outside quantization range")
        quantized[index] = reconstructed
    return quantized


def _encode_face_stream(faces: np.ndarray, level: int) -> bytes:
    face_delta_stream = bytearray()
    previous = 0
    for raw_index in faces.reshape(-1):
        current = int(raw_index)
        face_delta_stream.extend(_encode_varint(_zigzag_encode(current - previous)))
        previous = current
    return zlib.compress(bytes(face_delta_stream), level)


def _reorder_faces_for_stream(
    vertices: np.ndarray, faces: np.ndarray, face_ordering: str = "source"
) -> np.ndarray:
    """Order triangle rows and/or cyclic starts for delta-varint connectivity.

    "source" preserves face rows and cyclic starts.
    "rotate" preserves face row order but tests all three cyclic starts to
    minimize signed-varint cost relative to the previous index.
    "bfs" traverses the triangle dual graph and performs the same cyclic-start
    optimization. Triangles are never reversed, so winding is preserved.
    """
    if face_ordering not in FACE_CODING_OPTIONS:
        raise CodecError(f"face_ordering must be one of: {', '.join(FACE_CODING_OPTIONS)}")
    faces = np.asarray(faces, dtype=np.int64)
    if face_ordering == "source":
        return faces.copy()

    face_count = len(faces)
    if face_count < 2:
        return faces.copy()

    if face_ordering == "rotate":
        traversal = list(range(face_count))
    else:
        edge_faces: dict[tuple[int, int], list[int]] = {}
        for face_index, tri in enumerate(faces):
            a, b, c = (int(x) for x in tri)
            for u, v in ((a, b), (b, c), (c, a)):
                if u == v:
                    continue
                edge = (u, v) if u < v else (v, u)
                edge_faces.setdefault(edge, []).append(face_index)

        adjacent = [set() for _ in range(face_count)]
        for incident in edge_faces.values():
            unique = sorted(set(incident))
            for index, left in enumerate(unique):
                for right in unique[index + 1:]:
                    adjacent[left].add(right)
                    adjacent[right].add(left)

        areas = np.zeros(face_count, dtype=np.float64)
        for face_index, tri in enumerate(faces):
            a, b, c = (int(x) for x in tri)
            areas[face_index] = float(np.linalg.norm(
                np.cross(vertices[b] - vertices[a], vertices[c] - vertices[a])
            ))

        visited = np.zeros(face_count, dtype=bool)
        traversal = []
        from collections import deque
        while len(traversal) < face_count:
            unseen = np.flatnonzero(~visited)
            if unseen.size == 0:
                break
            seed = max((int(i) for i in unseen), key=lambda i: (areas[i], -i))
            queue = deque([seed])
            visited[seed] = True
            while queue:
                face_index = queue.popleft()
                traversal.append(face_index)
                for neighbor in sorted(adjacent[face_index]):
                    if not visited[neighbor]:
                        visited[neighbor] = True
                        queue.append(neighbor)

    reordered: list[tuple[int, int, int]] = []
    previous = 0
    for face_index in traversal:
        a, b, c = (int(x) for x in faces[face_index])
        rotations = ((a, b, c), (b, c, a), (c, a, b))

        def delta_cost(tri: tuple[int, int, int]) -> int:
            total = 0
            last = previous
            for value in tri:
                total += len(_encode_varint(_zigzag_encode(value - last)))
                last = value
            return total

        chosen = min(enumerate(rotations), key=lambda item: (delta_cost(item[1]), item[0]))[1]
        reordered.append(chosen)
        previous = chosen[-1]
    return np.asarray(reordered, dtype=np.int64)


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
    predictors = np.zeros_like(quantized, dtype=np.int64)
    parented = np.flatnonzero(parents >= 0)
    predictors[parented] = quantized[parents[parented]]
    residuals = (quantized - predictors).reshape(-1)
    residual_stream = bytearray()
    for residual in residuals:
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


def _parallelogram_stencils(faces: np.ndarray, vertex_count: int) -> list[tuple[int, int, int] | None]:
    """Find a deterministic prior base triangle sharing an edge with each vertex.

    A stencil (left, right, base) predicts the opposite vertex as
    left + right - base. All stencil vertices have lower indices than target.
    """
    edge_opposites: dict[tuple[int, int], list[int]] = {}
    for tri in faces:
        a, b, c = (int(x) for x in tri)
        if len({a, b, c}) != 3:
            continue
        for u, v, opposite in ((a, b, c), (b, c, a), (c, a, b)):
            edge = (u, v) if u < v else (v, u)
            edge_opposites.setdefault(edge, []).append(opposite)

    candidates: list[list[tuple[int, int, int]]] = [[] for _ in range(vertex_count)]
    for (left, right), opposites in edge_opposites.items():
        unique = sorted(set(opposites))
        for target in unique:
            if target <= max(left, right):
                continue
            for base in unique:
                if base != target and left < target and right < target and base < target:
                    candidates[target].append((left, right, base))
    return [min(options) if options else None for options in candidates]


def _vertex_valences(faces: np.ndarray, vertex_count: int) -> np.ndarray:
    """Count unique mesh neighbors per vertex, independent of face order."""
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]), axis=0)
    lo = np.minimum(edges[:, 0], edges[:, 1])
    hi = np.maximum(edges[:, 0], edges[:, 1])
    valid = hi > lo
    undirected = np.unique(np.column_stack((lo[valid], hi[valid])), axis=0)
    valences = np.zeros(vertex_count, dtype=np.int64)
    if len(undirected):
        np.add.at(valences, undirected[:, 0], 1)
        np.add.at(valences, undirected[:, 1], 1)
    return valences


def _angle_between(a: np.ndarray, b: np.ndarray) -> float:
    """Stable unsigned angle between two 3D vectors."""
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator < 1e-14 or not np.isfinite(denominator):
        return np.pi / 3.0
    cosine = float(np.dot(a, b)) / denominator
    return float(np.arccos(np.clip(cosine, -1.0 + 1e-12, 1.0 - 1e-12)))


def _weighted_parallelogram_prediction(
    left: np.ndarray,
    right: np.ndarray,
    base: np.ndarray,
    left_index: int,
    right_index: int,
    target_index: int,
    valences: np.ndarray,
) -> np.ndarray:
    """Valence-weighted parallelogram predictor inspired by Vasa et al.

    Known base-triangle angles alpha and beta are combined with valence-derived
    estimates gamma and delta for the new triangle. The formula is
        p = w1*left + w2*right + (1-w1-w2)*base
        w1 = (cot(beta)+cot(delta))/(cot(delta)+cot(gamma))
        w2 = (cot(alpha)+cot(gamma))/(cot(delta)+cot(gamma)).
    Invalid or ill-conditioned stencils fall back to the classic predictor.
    """
    fallback = left + right - base
    alpha = _angle_between(right - left, base - left)
    beta = _angle_between(left - right, base - right)

    # Estimate each new-triangle angle from local valence, then normalize to pi.
    degree_values = np.asarray(
        [
            max(int(valences[left_index]), 1),
            max(int(valences[right_index]), 1),
            max(int(valences[target_index]), 1),
        ],
        dtype=np.float64,
    )
    inverse = 1.0 / degree_values
    angle_estimates = np.pi * inverse / float(inverse.sum())
    gamma, delta = float(angle_estimates[0]), float(angle_estimates[1])

    sin_gamma = float(np.sin(gamma))
    sin_delta = float(np.sin(delta))
    cot_gamma = float(np.cos(gamma)) / (sin_gamma if abs(sin_gamma) > 1e-8 else 1e-8)
    cot_delta = float(np.cos(delta)) / (sin_delta if abs(sin_delta) > 1e-8 else 1e-8)
    denominator = cot_delta + cot_gamma
    if not np.isfinite(denominator) or abs(denominator) < 1e-7:
        return fallback
    cot_alpha = float(np.cos(alpha)) / max(abs(float(np.sin(alpha))), 1e-8)
    cot_beta = float(np.cos(beta)) / max(abs(float(np.sin(beta))), 1e-8)
    w1 = (cot_beta + cot_delta) / denominator
    w2 = (cot_alpha + cot_gamma) / denominator
    if not np.isfinite(w1) or not np.isfinite(w2) or max(abs(w1), abs(w2), abs(1.0 - w1 - w2)) > 8.0:
        return fallback
    return w1 * left + w2 * right + (1.0 - w1 - w2) * base


def _local_tangent_frame(left: np.ndarray, right: np.ndarray, base: np.ndarray,
                         prediction: np.ndarray) -> np.ndarray:
    """Orthonormal frame with the base triangle normal as its first axis."""
    edge = left - right
    normal = np.cross(edge, base - right)
    eps = 1e-14
    normal_norm = float(np.linalg.norm(normal))
    if normal_norm <= eps:
        edge_norm = float(np.linalg.norm(edge))
        if edge_norm > eps:
            direction = edge / edge_norm
            axis = np.eye(3)[int(np.argmin(np.abs(direction)))]
            normal = np.cross(direction, axis)
        else:
            normal = np.array([0.0, 0.0, 1.0])
        normal_norm = float(np.linalg.norm(normal))
    x1 = normal / max(normal_norm, eps)

    direction = prediction - base
    direction -= float(np.dot(direction, x1)) * x1
    direction_norm = float(np.linalg.norm(direction))
    if direction_norm <= eps:
        direction = edge - float(np.dot(edge, x1)) * x1
        direction_norm = float(np.linalg.norm(direction))
    if direction_norm <= eps:
        axis = np.eye(3)[int(np.argmin(np.abs(x1)))]
        direction = axis - float(np.dot(axis, x1)) * x1
        direction_norm = float(np.linalg.norm(direction))
    x2 = direction / max(direction_norm, eps)
    x3 = np.cross(x1, x2)
    x3 /= max(float(np.linalg.norm(x3)), eps)
    x2 = np.cross(x3, x1)
    x2 /= max(float(np.linalg.norm(x2)), eps)
    return np.column_stack((x1, x2, x3))


def _tangent_residual_step(mins: np.ndarray, maxs: np.ndarray, bits: int) -> float:
    """Choose a scalar step whose 3D rounding bound matches the axis-grid bound.

    For grid levels L=2^bits-1, a scalar local-frame step
    s = ||bbox_span|| / (sqrt(3) L) yields a worst-case residual rounding
    error sqrt(3)*s/2 = ||bbox_span||/(2L), matching the original axis-wise
    quantizer's Euclidean half-diagonal bound. This avoids over-quantizing
    skinny meshes by using only their smallest axis extent.
    """
    spans = np.asarray(maxs - mins, dtype=np.float64)
    diagonal = float(np.linalg.norm(spans))
    if not np.isfinite(diagonal) or diagonal <= 0.0:
        raise CodecError("mesh must have finite, non-zero geometric extent")
    step = diagonal / (np.sqrt(3.0) * ((1 << bits) - 1))
    if not np.isfinite(step) or step <= 0.0:
        raise CodecError("could not derive a finite tangent residual quantization step")
    return step


def _encode_tangent_coordinates(
    vertices: np.ndarray, quantized: np.ndarray, mins: np.ndarray, maxs: np.ndarray,
    faces: np.ndarray, bits: int, level: int, weighted: bool = False,
    normal_fine: bool = False, normal_step_ratio: float = 0.5,
    sparse_mode: bool = False, adaptive_sparse_mode: bool = False
) -> tuple[bytes, float | np.ndarray, int]:
    """Encode locally framed parallelogram-prediction residuals as signed varints.

    When normal_fine is enabled, the normal component gets half the scalar step
    and the two tangential components share the remaining squared-error budget.
    The sum of squared step sizes remains 3*s^2, preserving the same conservative
    Euclidean rounding-error bound as the equal-step tangent coder.
    """
    levels = (1 << bits) - 1
    spans = maxs - mins
    base_step = _tangent_residual_step(mins, maxs, bits)
    if normal_fine:
        if not np.isfinite(normal_step_ratio) or not 0.0 < normal_step_ratio <= 1.0:
            raise CodecError("normal_step_ratio must be in the interval (0, 1]")
        normal_step = base_step * normal_step_ratio
        tangent_step = base_step * np.sqrt((3.0 - normal_step_ratio ** 2) / 2.0)
        steps = np.asarray([normal_step, tangent_step, tangent_step], dtype=np.float64)
        step: float | np.ndarray = steps
    else:
        step = base_step
        steps = np.full(3, base_step, dtype=np.float64)
    stencils = _parallelogram_stencils(faces, len(vertices))
    valences = _vertex_valences(faces, len(vertices)) if weighted else None
    reconstructed = np.empty_like(vertices, dtype=np.float64)
    raw = bytearray()
    sparse_values: list[int] = []
    adaptive_seed_values: list[int] = []
    adaptive_residual_values: list[int] = []
    predicted_count = 0
    for i, stencil in enumerate(stencils):
        if stencil is None:
            q = quantized[i]
            reconstructed[i] = mins + (q.astype(np.float64) / levels) * spans
            for value in q:
                if adaptive_sparse_mode:
                    adaptive_seed_values.append(int(value))
                elif sparse_mode:
                    sparse_values.append(int(value))
                else:
                    raw.extend(_encode_varint(int(value)))
            continue
        left_i, right_i, base_i = stencil
        left, right, base = reconstructed[left_i], reconstructed[right_i], reconstructed[base_i]
        prediction = (
            _weighted_parallelogram_prediction(left, right, base, left_i, right_i, i, valences)
            if weighted and valences is not None else left + right - base
        )
        frame = _local_tangent_frame(left, right, base, prediction)
        local_residual = frame.T @ (vertices[i] - prediction)
        residual_codes = np.rint(local_residual / steps).astype(np.int64)
        for value in residual_codes:
            if adaptive_sparse_mode:
                adaptive_residual_values.append(int(value))
            elif sparse_mode:
                sparse_values.append(int(value))
            else:
                raw.extend(_encode_varint(_zigzag_encode(int(value))))
        reconstructed[i] = prediction + frame @ (residual_codes.astype(np.float64) * steps)
        predicted_count += 1
    if adaptive_sparse_mode:
        raw_payload = _encode_chandas_adaptive_stream(adaptive_seed_values, adaptive_residual_values)
    elif sparse_mode:
        raw_payload = _encode_chandas_sparse_signed(sparse_values)
    else:
        raw_payload = bytes(raw)
    return zlib.compress(raw_payload, level), step, predicted_count


def _decode_tangent_coordinates(
    coord_raw: bytes, faces: np.ndarray, vertex_count: int, bits: int,
    mins: np.ndarray, maxs: np.ndarray, step: float | np.ndarray, weighted: bool = False,
    sparse_mode: bool = False
) -> np.ndarray:
    raw_values = (
        _decode_chandas_sparse_signed(coord_raw, vertex_count * 3)
        if sparse_mode else _decode_varints(coord_raw, vertex_count * 3)
    )
    levels = (1 << bits) - 1
    spans = maxs - mins
    steps = np.full(3, float(step), dtype=np.float64) if np.isscalar(step) else np.asarray(step, dtype=np.float64)
    if steps.shape != (3,) or not np.isfinite(steps).all() or np.any(steps <= 0):
        raise CodecError("invalid tangent residual step vector")
    stencils = _parallelogram_stencils(faces, vertex_count)
    valences = _vertex_valences(faces, vertex_count) if weighted else None
    reconstructed = np.empty((vertex_count, 3), dtype=np.float64)
    cursor = 0
    for i, stencil in enumerate(stencils):
        values = raw_values[cursor:cursor + 3]
        cursor += 3
        if stencil is None:
            q = np.asarray(values, dtype=np.int64)
            if np.any(q < 0) or np.any(q > levels):
                raise CodecError("absolute seed coordinate is outside quantization range")
            reconstructed[i] = mins + (q.astype(np.float64) / levels) * spans
            continue
        left_i, right_i, base_i = stencil
        left, right, base = reconstructed[left_i], reconstructed[right_i], reconstructed[base_i]
        prediction = (
            _weighted_parallelogram_prediction(left, right, base, left_i, right_i, i, valences)
            if weighted and valences is not None else left + right - base
        )
        frame = _local_tangent_frame(left, right, base, prediction)
        residual_codes = np.asarray(
            values if sparse_mode else [_zigzag_decode(int(v)) for v in values],
            dtype=np.float64,
        )
        reconstructed[i] = prediction + frame @ (residual_codes * steps)
    return reconstructed


def _decode_chandas_adaptive_tangent_coordinates(
    coord_raw: bytes, faces: np.ndarray, vertex_count: int, bits: int,
    mins: np.ndarray, maxs: np.ndarray, step: float
) -> np.ndarray:
    """Decode MO3D v7: absolute seed coordinates + locally adaptive residual blocks."""
    if not coord_raw.startswith(b"CHS2"):
        raise CodecError("invalid Chandas adaptive tangent signature")
    cursor = 4
    stencils = _parallelogram_stencils(faces, vertex_count)
    seed_indices = [index for index, stencil in enumerate(stencils) if stencil is None]
    seed_count, cursor = _read_varint(coord_raw, cursor)
    if seed_count != len(seed_indices):
        raise CodecError("Chandas seed count does not match the mesh connectivity")
    levels = (1 << bits) - 1
    spans = maxs - mins
    reconstructed = np.empty((vertex_count, 3), dtype=np.float64)
    for index in seed_indices:
        q = []
        for _axis in range(3):
            value, cursor = _read_varint(coord_raw, cursor)
            if value > levels:
                raise CodecError("Chandas seed coordinate is outside quantization range")
            q.append(value)
        reconstructed[index] = mins + (np.asarray(q, dtype=np.float64) / levels) * spans

    residual_count, cursor = _read_varint(coord_raw, cursor)
    expected_residual_count = (vertex_count - seed_count) * 3
    if residual_count != expected_residual_count:
        raise CodecError("Chandas residual count does not match predictive vertex count")
    residual_values, cursor = _decode_chandas_adaptive_residuals(
        coord_raw, cursor, expected_residual_count
    )
    if cursor != len(coord_raw):
        raise CodecError("unexpected trailing bytes in Chandas adaptive stream")

    valences = _vertex_valences(faces, vertex_count)
    residual_cursor = 0
    steps = np.full(3, step, dtype=np.float64)
    for index, stencil in enumerate(stencils):
        if stencil is None:
            continue
        left_i, right_i, base_i = stencil
        left, right, base = reconstructed[left_i], reconstructed[right_i], reconstructed[base_i]
        prediction = _weighted_parallelogram_prediction(
            left, right, base, left_i, right_i, index, valences
        )
        frame = _local_tangent_frame(left, right, base, prediction)
        residual_codes = np.asarray(residual_values[residual_cursor:residual_cursor + 3], dtype=np.float64)
        residual_cursor += 3
        reconstructed[index] = prediction + frame @ (residual_codes * steps)
    return reconstructed


def encode_mesh(vertices: Any, faces: Any, bits: int = 16, level: int = 6, method: str = "baseline", ordering: str = "source", normal_step_ratio: float = 0.5, face_ordering: str = "source") -> bytes:
    """Encode a triangle mesh as MO3D bytes.

    Args:
        vertices: N x 3 numeric coordinate array.
        faces: M x 3 triangle indices.
        bits: Per-axis position precision, 8–24 bits.
        level: zlib compression level, 0–9.
        method: "baseline", "prithvi", "parallelogram", or "auto". The
            parallelogram mode averages causal neighboring-face parallelogram
            predictions; auto selects the smallest resulting bitstream.
        ordering: "source", "bfs", "morton", or "predictive" controls vertex order.
        face_ordering: "source" preserves face row order; "bfs" traverses the
            triangle dual graph and optimizes cyclic starts for index-delta coding.

    Geometry is lossy because coordinates are quantized. Normals, UVs, colors,
    textures, material data and source-format metadata are omitted.
    """
    if not isinstance(bits, int) or isinstance(bits, bool) or not 8 <= bits <= 24:
        raise CodecError("bits must be an integer from 8 through 24")
    if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 9:
        raise CodecError("zlib level must be an integer from 0 through 9")
    if method not in METHODS:
        raise CodecError(f"method must be one of: {', '.join(METHODS)}")
    if ordering not in ORDERINGS:
        raise CodecError(f"ordering must be one of: {', '.join(ORDERINGS)}")
    if face_ordering not in FACE_ORDERINGS:
        raise CodecError(f"face_ordering must be one of: {', '.join(FACE_ORDERINGS)}")
    if not isinstance(normal_step_ratio, (int, float)) or isinstance(normal_step_ratio, bool) or not np.isfinite(normal_step_ratio) or not 0.0 < normal_step_ratio <= 1.0:
        raise CodecError("normal_step_ratio must be in the interval (0, 1]")
    if face_ordering == "auto" and method != "auto":
        candidates = [
            (
                len(payload),
                option_index,
                payload,
            )
            for option_index, option in enumerate(FACE_CODING_OPTIONS)
            for payload in [
                encode_mesh(
                    vertices, faces, bits=bits, level=level, method=method,
                    ordering=ordering, normal_step_ratio=normal_step_ratio,
                    face_ordering=option,
                )
            ]
        ]
        return min(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]
    if method == "auto":
        best_payload = None
        best_key = None
        normal_ratios = (0.375, 0.5, 0.625, 0.75, 0.875)
        levels = (1 << bits) - 1
        spans = vertices.max(axis=0) - vertices.min(axis=0)
        max_error_budget = float(np.linalg.norm(spans / (2 * levels)))
        for ordering_index, candidate_ordering in enumerate(AUTO_ORDERINGS):
            traversal = vertex_order_for_mesh(vertices, faces, candidate_ordering)
            ordered_vertices = vertices[traversal]
            for face_order_index, candidate_face_ordering in enumerate(AUTO_FACE_ORDERINGS):
                for method_index, candidate_method in enumerate(CODEC_METHODS):
                    candidate_ratios = normal_ratios if candidate_method == "normal_fine_tangent" else (float(normal_step_ratio),)
                    for ratio_index, candidate_ratio in enumerate(candidate_ratios):
                        try:
                            candidate = encode_mesh(
                                vertices, faces, bits=bits, level=level,
                                method=candidate_method, ordering=candidate_ordering,
                                normal_step_ratio=candidate_ratio,
                                face_ordering=candidate_face_ordering
                            )
                            decoded_vertices, _, _ = decode_mesh(candidate)
                        except CodecError:
                            continue
                        candidate_error = np.linalg.norm(decoded_vertices - ordered_vertices, axis=1)
                        if candidate_error.size and float(candidate_error.max()) > max_error_budget * 1.0001 + 1e-12:
                            continue
                        key = (len(candidate), method_index, ordering_index, face_order_index, ratio_index)
                        if best_key is None or key < best_key:
                            best_key = key
                            best_payload = candidate
        if best_payload is None:
            raise CodecError("no available encoder could encode this mesh")
        return best_payload
    vertices, faces, _ = reorder_mesh(vertices, faces, ordering)
    quantized, mins, maxs = _quantize(vertices, bits)
    tangent_step = None
    tangent_predictive_vertices = 0
    if method == "prithvi":
        coord_stream = _encode_prithvi_coordinates(quantized, faces, level)
        coordinate_coder = "prithvi-mesh-adjacency-residual-varint-zlib"
    elif method in {"tangent", "weighted_tangent", "normal_fine_tangent", "chandas_tangent", "chandas_adaptive_tangent"}:
        weighted = method in {"weighted_tangent", "normal_fine_tangent", "chandas_tangent", "chandas_adaptive_tangent"}
        normal_fine = method == "normal_fine_tangent"
        sparse_mode = method == "chandas_tangent"
        adaptive_sparse_mode = method == "chandas_adaptive_tangent"
        coord_stream, tangent_step, tangent_predictive_vertices = _encode_tangent_coordinates(
            vertices, quantized, mins, maxs, faces, bits, level,
            weighted=weighted, normal_fine=normal_fine, normal_step_ratio=float(normal_step_ratio),
            sparse_mode=sparse_mode, adaptive_sparse_mode=adaptive_sparse_mode
        )
        coordinate_coder = (
            "chandas-adaptive-weighted-tangent-residual-varint-zlib"
            if adaptive_sparse_mode else
            "chandas-weighted-tangent-sparse-enumerative-varint-zlib"
            if sparse_mode else
            "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib"
            if normal_fine else
            "weighted-tangent-parallelogram-residual-varint-zlib"
            if weighted else "tangent-parallelogram-residual-varint-zlib"
        )
    else:
        coord_dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
        coord_stream = zlib.compress(quantized.astype(coord_dtype).tobytes(order="C"), level)
        coordinate_coder = "absolute-fixed-width-zlib"
    faces_for_stream = _reorder_faces_for_stream(vertices, faces, face_ordering)
    face_stream = _encode_face_stream(faces_for_stream, level)

    header = {
        "format": "MO3D",
        "version": {"baseline": 1, "prithvi": 2, "tangent": 3, "weighted_tangent": 4, "normal_fine_tangent": 5, "chandas_tangent": 6, "chandas_adaptive_tangent": 7}[method],
        "position_bits": bits,
        "vertex_ordering": ordering,
        "vertex_count": int(len(vertices)),
        "face_count": int(len(faces)),
        "bounds_min": mins.tolist(),
        "bounds_max": maxs.tolist(),
        "coordinate_stream_bytes": len(coord_stream),
        "face_stream_bytes": len(face_stream),
        "tangent_residual_step": float(tangent_step) if np.isscalar(tangent_step) else None,
        "tangent_residual_steps": tangent_step.tolist() if isinstance(tangent_step, np.ndarray) else None,
        "tangent_predictive_vertices": tangent_predictive_vertices,
        "normal_step_ratio": float(tangent_step[0] / _tangent_residual_step(mins, maxs, bits)) if method == "normal_fine_tangent" and isinstance(tangent_step, np.ndarray) else None,
        "coordinate_coder": coordinate_coder,
        "position_quantization": "uniform per axis, bounding-box normalized",
        "topology": "triangles, delta indices with zigzag varints, zlib",
        "method_note": (
            "Prithvi is an engineering analogy inspired by Atharvaveda 12.1, not a claim of a compression algorithm in the text."
            if method == "prithvi" else
            "Weighted tangent predictor with half-step normal quantization and equal total squared error budget."
            if method == "normal_fine_tangent" else
            "Valence-weighted parallelogram predictor with local tangent-frame residuals."
            if method == "weighted_tangent" else
            "Research-inspired parallelogram predictor with local tangent-frame residuals."
            if method == "tangent" else
            "Baseline absolute-coordinate coder."
        ),
    }
    # Preserve the original compact source-order header; the new field is
    # necessary only when the optional face traversal changes the face stream.
    if face_ordering != "source":
        header["face_ordering"] = face_ordering
    header_bytes = json.dumps(header, separators=(",", ":"), allow_nan=False).encode("utf-8")
    magic = {"baseline": MAGIC_V1, "prithvi": MAGIC_V2, "tangent": MAGIC_V3, "weighted_tangent": MAGIC_V4, "normal_fine_tangent": MAGIC_V5, "chandas_tangent": MAGIC_V6, "chandas_adaptive_tangent": MAGIC_V7}[method]
    return magic + struct.pack(">I", len(header_bytes)) + header_bytes + coord_stream + face_stream


def decode_mesh(payload: bytes) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Decode MO3D bytes; returns reconstructed vertices, faces and metadata."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes-like")
    payload = bytes(payload)
    magic_len = len(MAGIC_V1)
    if len(payload) < magic_len + 4:
        raise CodecError("not a supported MO3D bitstream")
    magic = payload[:magic_len]
    if magic not in (MAGIC_V1, MAGIC_V2, MAGIC_V3, MAGIC_V4, MAGIC_V5, MAGIC_V6, MAGIC_V7):
        raise CodecError("not a supported MO3D bitstream")
    header_len = struct.unpack(">I", payload[magic_len:magic_len + 4])[0]
    start = magic_len + 4
    if header_len < 2 or header_len > MAX_HEADER_BYTES or start + header_len > len(payload):
        raise CodecError("invalid metadata header length")
    try:
        header = json.loads(payload[start:start + header_len].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodecError("invalid metadata header") from exc
    if not isinstance(header, dict) or header.get("format") != "MO3D" or header.get("version") not in (1, 2, 3, 4, 5, 6, 7):
        raise CodecError("unsupported MO3D format version")
    version = header["version"]
    expected_version = {MAGIC_V1: 1, MAGIC_V2: 2, MAGIC_V3: 3, MAGIC_V4: 4, MAGIC_V5: 5, MAGIC_V6: 6, MAGIC_V7: 7}[magic]
    if version != expected_version:
        raise CodecError("MO3D magic and header version do not match")
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
    if version == 1 and coder != "absolute-fixed-width-zlib":
        raise CodecError("non-baseline coordinate coding requires MO3D format version 2 or higher")
    if version == 2 and coder != "prithvi-mesh-adjacency-residual-varint-zlib":
        raise CodecError("MO3D format version 2 requires the Prithvi residual coordinate coder")
    if version == 3 and coder != "tangent-parallelogram-residual-varint-zlib":
        raise CodecError("MO3D format version 3 requires the tangent-space residual coder")
    if version == 4 and coder != "weighted-tangent-parallelogram-residual-varint-zlib":
        raise CodecError("MO3D format version 4 requires the weighted tangent-space residual coder")
    if version == 5 and coder != "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib":
        raise CodecError("MO3D format version 5 requires the normal-fine tangent residual coder")
    if version == 6 and coder != "chandas-weighted-tangent-sparse-enumerative-varint-zlib":
        raise CodecError("MO3D format version 6 requires the Chandas sparse-enumerative tangent coder")
    if version == 7 and coder != "chandas-adaptive-weighted-tangent-residual-varint-zlib":
        raise CodecError("MO3D format version 7 requires the adaptive Chandas residual coder")
    if coder == "absolute-fixed-width-zlib":
        dtype = np.dtype("<u1" if bits <= 8 else "<u2" if bits <= 16 else "<u4")
        expected_coord_bytes = vertex_count * 3 * dtype.itemsize
        if len(coord_raw) != expected_coord_bytes:
            raise CodecError("coordinate data length does not match vertex count")
        quantized = np.frombuffer(coord_raw, dtype=dtype).astype(np.int64).reshape(vertex_count, 3)
        if np.any(quantized > levels):
            raise CodecError("absolute coordinate is outside quantization range")
        vertices = mins + (quantized.astype(np.float64) / levels) * (maxs - mins)
    elif coder == "prithvi-mesh-adjacency-residual-varint-zlib":
        quantized = _decode_prithvi_coordinates(coord_raw, faces, vertex_count, bits)
        vertices = mins + (quantized.astype(np.float64) / levels) * (maxs - mins)
    elif coder == "chandas-adaptive-weighted-tangent-residual-varint-zlib":
        step = header.get("tangent_residual_step")
        if not isinstance(step, (int, float)) or not np.isfinite(step) or step <= 0:
            raise CodecError("invalid Chandas adaptive tangent residual step")
        vertices = _decode_chandas_adaptive_tangent_coordinates(
            coord_raw, faces, vertex_count, bits, mins, maxs, float(step)
        )
    elif coder in {
        "tangent-parallelogram-residual-varint-zlib",
        "weighted-tangent-parallelogram-residual-varint-zlib",
        "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib",
        "chandas-weighted-tangent-sparse-enumerative-varint-zlib",
    }:
        sparse_mode = coder == "chandas-weighted-tangent-sparse-enumerative-varint-zlib"
        weighted = coder != "tangent-parallelogram-residual-varint-zlib"
        if coder == "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib":
            step = header.get("tangent_residual_steps")
            if not isinstance(step, list) or len(step) != 3:
                raise CodecError("invalid normal-fine tangent residual step vector")
            step = np.asarray(step, dtype=np.float64)
        else:
            step = header.get("tangent_residual_step")
        if np.isscalar(step):
            if not isinstance(step, (int, float)) or not np.isfinite(step) or step <= 0:
                raise CodecError("invalid tangent residual quantization step")
        elif np.asarray(step).shape != (3,) or not np.isfinite(step).all() or np.any(np.asarray(step) <= 0):
            raise CodecError("invalid tangent residual quantization step vector")
        vertices = _decode_tangent_coordinates(
            coord_raw, faces, vertex_count, bits, mins, maxs, step, weighted=weighted,
            sparse_mode=sparse_mode
        )
    else:
        raise CodecError(f"unsupported coordinate coder: {coder!r}")
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


def encode_file(input_path: str | Path, output_path: str | Path, bits: int = 16, method: str = "baseline", ordering: str = "source", normal_step_ratio: float = 0.5, face_ordering: str = "source") -> dict[str, Any]:
    vertices, faces, _ = load_mesh(input_path)
    encoded = encode_mesh(vertices, faces, bits=bits, method=method, ordering=ordering, normal_step_ratio=normal_step_ratio, face_ordering=face_ordering)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    actual_method = method
    actual_ordering = ordering
    if method == "auto":
        _, _, metadata = decode_mesh(encoded)
        coder_to_method = {
            "absolute-fixed-width-zlib": "baseline",
            "prithvi-mesh-adjacency-residual-varint-zlib": "prithvi",
            "tangent-parallelogram-residual-varint-zlib": "tangent",
            "weighted-tangent-parallelogram-residual-varint-zlib": "weighted_tangent",
            "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib": "normal_fine_tangent",
            "chandas-weighted-tangent-sparse-enumerative-varint-zlib": "chandas_tangent",
            "chandas-adaptive-weighted-tangent-residual-varint-zlib": "chandas_adaptive_tangent",
        }
        actual_method = coder_to_method[metadata["coordinate_coder"]]
        actual_ordering = metadata.get("vertex_ordering", "source")
    _, _, encoded_metadata = decode_mesh(encoded)
    actual_normal_step_ratio = encoded_metadata.get("normal_step_ratio")
    return {"input": str(input_path), "output": str(output_path), "input_bytes": Path(input_path).stat().st_size,
            "output_bytes": len(encoded), "ratio": Path(input_path).stat().st_size / len(encoded),
            "position_bits": bits, "requested_method": method, "method": actual_method, "ordering": actual_ordering,
            "normal_step_ratio": actual_normal_step_ratio, "face_ordering": encoded_metadata.get("face_ordering", "source"),
            "vertices": len(vertices), "faces": len(faces)}


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
