# Test and validation report

**Updated:** 25 October 2026

## Automated CI validation

- **Unit tests:** 18 tests cover Python 3.10, 3.12, and 3.13 in the [latest test run](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40171463185).
- **CLI smoke tests:** baseline, weighted tangent + BFS, normal-fine tangent + BFS, and adaptive encode/decode commands are exercised on generated mesh fixtures.
- **Research-coder benchmark:** the benchmark compares baseline, Prithvi, tangent, weighted tangent, normal-fine tangent, and Google Draco under source, BFS and Morton orderings. The normal-fine method tests five normal-step ratios and reports error in the local normal and tangent directions. See the [current GitHub Actions benchmark](https://github.com/lalitkumar790/MiddleOut-3D/actions).

## What the tests cover

- Baseline encode/decode preserves triangle indices and stays within the quantization error bound.
- Higher coordinate precision does not worsen the tested reconstruction error.
- Prithvi reconstructed quantized vertex coordinates exactly match the absolute-coordinate baseline at the same precision.
- Legacy MO3D v1 decoding remains supported, and version-signature mismatches are rejected.
- Source, breadth-first (BFS), and Morton orderings each produce a valid vertex-index permutation with consistently remapped face indices.
- Baseline and Prithvi both round-trip correctly under all three orderings, including topology restoration after mapping back to source indexing.
- Tangent, weighted-tangent and normal-fine tangent streams round-trip under all three orderings and remain within the baseline's conservative Euclidean quantization-error bound on the test fixture.
- The normal-fine local-frame quantizer tests the steps ratios 0.375, 0.5, 0.625, 0.75, and 0.875; each candidate preserves the same sum of squared step sizes as the equal-step variant.
- Benchmark metrics include local normal-component RMSE, tangential-component RMSE, and the selected ratio. The benchmark chooses the smallest ratio candidate within the baseline's maximum-error budget.
- Adaptive mode returns the smallest bitstream among the four ordinary coders and five normal-step ratios under all three orderings tested for a mesh (up to 27 candidate streams).
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


## Predictive ordering experiment

- [Predictive-ordering benchmark](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40195070244) completed successfully; the archived result is available in [JSON](results/predictive_ordering_study_2026-10-25.json) and [CSV](results/predictive_ordering_study_2026-10-25.csv).
- Predictive ordering increased aggregate encoded sizes compared with both source and BFS order for all seven in-house coders in the six-fixture synthetic set.
- Its one-repeat baseline encoding time summed to 411.06 ms across the six fixtures, versus 44.92 ms for BFS and 16.51 ms for source order.
- It was removed from the auto-selection search but remains an experimental ordering. This preserves the negative result rather than letting an unproductive heuristic slow normal encoding.
- Latest functional test matrix before the report-only commits passed across Python 3.10, 3.12, and 3.13, including remapping/round-trip tests for predictive ordering and auto selection.



## Face-stream order validation

- The face-stream benchmark [completed successfully](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40196914983). Archived tables are in [JSON](results/face_connectivity_study_2026-10-25.json) and [CSV](results/face_connectivity_study_2026-10-25.csv).
- Six synthetic meshes were tested with seven coordinate coders, three vertex orderings, and source/rotate/BFS face strategies. All topology and error-budget checks passed.
- Rotate-only was smaller in aggregate within every fixed coder/vertex-order pair; BFS face traversal was larger in all 21 pairs.
- The unit-test matrix passed on Python 3.10, 3.12, and 3.13 in [run 40196963608](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40196963608). It covers triangle winding, face-stream round trips, geometry-error bounds, and auto selection of the shortest complete bitstream.
