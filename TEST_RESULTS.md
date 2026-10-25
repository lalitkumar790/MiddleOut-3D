# Test and validation report

**Updated:** 25 October 2026

## Automated CI validation

- **Unit tests:** 17 tests passed on Python 3.10, 3.12, and 3.13 in the [latest test run](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40169914630).
- **CLI smoke tests:** baseline, weighted tangent + BFS, and adaptive encode/decode commands are exercised on generated mesh fixtures.
- **Research-coder benchmark:** the benchmark now compares baseline, Prithvi, tangent, weighted tangent, and Google Draco under source, BFS and Morton orderings. See the [current GitHub Actions benchmark](https://github.com/lalitkumar790/MiddleOut-3D/actions).

## What the tests cover

- Baseline encode/decode preserves triangle indices and stays within the quantization error bound.
- Higher coordinate precision does not worsen the tested reconstruction error.
- Prithvi reconstructed quantized vertex coordinates exactly match the absolute-coordinate baseline at the same precision.
- Legacy MO3D v1 decoding remains supported, and version-signature mismatches are rejected.
- Source, breadth-first (BFS), and Morton orderings each produce a valid vertex-index permutation with consistently remapped face indices.
- Baseline and Prithvi both round-trip correctly under all three orderings, including topology restoration after mapping back to source indexing.
- Tangent and weighted-tangent streams round-trip under all three orderings and remain within the baseline's conservative Euclidean quantization-error bound on the test fixture.
- Adaptive mode returns the smallest bitstream among all four in-house coders and three orderings tested for a mesh.
- Unsupported methods and bit depths, corrupt bitstreams, zero-extent tangent meshes, and invalid version combinations are rejected.

## First research-inspired codec results

At 16 bits per axis, on six deterministic synthetic fixtures, the latest pre-Draco benchmark sums were:

| Configuration | Total bytes across six fixtures |
|---|---:|
| Source-order absolute baseline | 62,322 B |
| Source-order Prithvi | 47,802 B |
| BFS + tangent | 35,747 B |
| Source-order weighted tangent | 53,498 B |
| Adaptive per-mesh selection | 25,477 B |

Adaptive mode chose a mixture of methods and orderings. It is a size-first search, not the fastest encoder: tangent variants have higher Python execution cost. These totals are exploratory and are not claims of outperforming Draco; the direct Draco comparison is the current benchmark objective.

## Interpretation and limitations

- All in-house method/order combinations are required to preserve mesh topology and satisfy the measured geometry-error budget in CI.
- The benchmark compares Draco using a short quantization-bit sweep around the requested position precision and selects the smallest payload that meets the baseline's conservative maximum-error bound. Size is interpreted alongside measured maximum error and RMSE; Draco's topology-compression path may reorder point IDs, so decoded points are mapped back to source vertices for validation.
- The fixtures are synthetic, not a representative CAD, scanning, point-cloud, or robotics dataset.
- Timing is from a shared hosted runner and is not a universal performance claim.
- Current format is geometry-only and drops normals, UVs, colors, textures, materials and source-format metadata.
- The decoder has not been security-audited for hostile or arbitrarily large inputs.

These tests validate correctness under the tested conditions; they do not establish production readiness or universal superiority to an established codec.
