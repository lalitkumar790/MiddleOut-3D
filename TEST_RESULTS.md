# Test and validation report

**Updated:** 25 October 2026

## Automated CI validation

- **Unit tests:** 12 tests passed on Python 3.10, 3.12, and 3.13 in the [GitHub Actions test run](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40168239979).
- **CLI smoke test:** the workflow generates sample meshes, encodes an OBJ file, and decodes the result.
- **Ordering benchmark:** the [source/BFS/Morton comparison](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40168239993) completed successfully on Python 3.12, using six synthetic fixtures and five timed repetitions per operation.

## What the tests cover

- Baseline encode/decode preserves triangle indices and stays within the quantization error bound.
- Higher coordinate precision does not worsen the tested reconstruction error.
- Prithvi reconstructed quantized vertex coordinates exactly match the absolute-coordinate baseline at the same precision.
- Legacy MO3D v1 decoding remains supported, and version-signature mismatches are rejected.
- Source, breadth-first (BFS), and Morton orderings each produce a permutation of vertex indices with correctly remapped face indices.
- Baseline and Prithvi both round-trip correctly under all three orderings, including exact topology restoration after mapping back to source indices.
- Unsupported methods and bit depths, corrupt bitstreams, and invalid version combinations are rejected.

## First vertex-ordering experiment

At 16 bits per axis, across six deterministic synthetic fixtures:

| Ordering | Baseline total | Prithvi total | Prithvi reduction vs same-order baseline |
|---|---:|---:|---:|
| Source | 61,956 B | 47,436 B | 23.4360% |
| BFS | 49,634 B | 36,345 B | 26.7740% |
| Morton | 79,687 B | 69,734 B | 12.4901% |

BFS + Prithvi was the smallest measured configuration in this set. All 18 mesh/order/method combinations preserved triangle topology, and baseline and Prithvi produced identical quantized vertex coordinates at each ordering. Prithvi and BFS added encoding/decoding time compared with the source-order baseline in the hosted runner; Morton was larger in aggregate than source order.

Detailed measurements are in [BASELINE_RESULTS.md](BASELINE_RESULTS.md), with a machine-readable [JSON report](results/vertex_ordering_study_2026-10-25.json) and [CSV report](results/vertex_ordering_study_2026-10-25.csv).

## Not established

- No comparison with Google Draco or LZ4 has been performed.
- The fixtures are synthetic, not a representative CAD, scanning, point-cloud, or robotics dataset.
- Timing is from a shared hosted runner and is not a universal performance claim.
- The codec preserves triangle connectivity and quantized XYZ geometry but drops normals, UVs, colors, textures, materials, and source-format metadata.
- The decoder has not been security-audited for hostile or arbitrarily large inputs.

These checks validate correctness under tested conditions; they do not establish production readiness or superiority to existing compression codecs.
