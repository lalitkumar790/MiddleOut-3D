## 0.6.0 — Predictive-cost-guided ordering experiment

- Added an experimental `predictive` vertex ordering that greedily prioritizes available vertices with lower estimated local residual-varint cost.
- Extended traversal tests to cover predictive ordering in permutation validity, remapped-face correctness, and round-trip checks across the in-house coders.
- Expanded CI benchmark coverage to compare predictive ordering against source, BFS and Morton, with Draco under the same per-mesh error target.
- Documented its connection to pattern ordering as a modern hypothesis only; no claim is made that the method appears in Vedic or Desika-era texts.
- The new order is experimental and should only be retained if its complete file sizes and runtime justify the added search cost.

# Changelog

## 0.5.0 — Adaptive Chandas block coding

- Added MO3D v7 `chandas_adaptive_tangent`, separating absolute seed coordinates from predictive residuals.
- Added a per-64-symbol choice between direct signed varints and Piṅgala-inspired combinatorial ranking of non-zero positions; each block carries a mode flag.
- Added MO3D v7 signature/header validation and a compatible decoder while retaining v1–v6 support.
- Added cross-order round-trip tests, sparse/dense block tests, and CI smoke tests.
- Extended the Draco and in-house benchmark to record adaptive Chandas size, time, topology and reconstruction error.
- Documented the fixed v6 Chandas method's mixed/negative benchmark result; v7 is a new hypothesis and must be judged by its full-file measurements, not assumed superior.

## 0.4.0 — Chandas-inspired enumerative sparse residuals

- Added MO3D v6 `chandas_tangent`, combining the weighted local tangent-space predictor with a 64-symbol sparse pattern coder.
- Added combinatorial subset ranking/unranking, omitting zero residual positions and preserving exact decoding of the integer symbol stream.
- Extended `--method auto` to evaluate the Chandas candidate at all supported vertex orderings.
- Added tests for subset-pattern coding, malformed sparse streams, v6 signature/version compatibility, reconstruction error and topology across source/BFS/Morton orderings.
- Expanded benchmark reporting and GitHub Actions checks to compare Chandas with existing in-house methods and Google Draco.
- Documented the connection to Piṅgala's pattern enumeration as a modern inspiration, plus the limitations and sources. No claim is made that the exact codec appears in a Sanskrit text.

## 0.3.0 — Non-uniform local-frame quantization experiment

- Added MO3D v5 `normal_fine_tangent`: a weighted tangent-space predictor with finer quantization along the local surface normal and coarser steps in the two tangential directions.
- Added a five-point normal-step-ratio sweep (0.375–0.875) for adaptive selection; candidates are selected only when they meet the baseline maximum-error bound.
- Chose local residual steps so their squared step budget matches the equal-step tangent variant's theoretical Euclidean rounding-error bound, and recorded local normal/tangent reconstruction errors.
- Added v5 stream magic and decoder support while retaining v1–v4 decoding.
- Expanded benchmark reports and adaptive selection to five in-house coders across source, BFS, and Morton ordering.
- Added tests for v5 header/signature compatibility, non-uniform step sizes, topology preservation and measured geometric-error bounds.
- Expanded benchmark results to include the per-ratio sweep, selected ratio, and local normal-vs-tangential error metrics.
- Added CLI smoke testing for the new normal-fine method.

## 0.2.0 — Research-inspired predictors and codec comparison

- Added the MO3D v3 tangent-space residual coder using causal parallelogram prediction and a local orthonormal frame.
- Added the MO3D v4 valence-weighted tangent-space predictor, inspired by published weighted-parallelogram mesh compression research.
- Added size-first `--method auto`, which selects the shortest bitstream among the in-house coders and three vertex orderings.
- Added source, BFS and Morton vertex orderings with consistent face-index remapping.
- Expanded benchmark reports to include maximum vertex error, RMSE, encode/decode medians, topology checks and adaptive per-mesh selection.
- Added an optional `requirements-benchmark.txt` with DracoPy to compare the research codec with Google Draco using an error-budget quantization sweep.
- Added CI checks for tangent geometry-error bounds and CLI smoke tests for weighted and adaptive encoders.
- Documented research sources, implementation limits and fair rate-distortion comparison requirements.

## 0.1.0 — Initial research prototype

- Added the experimental MO3D v1 geometry-only mesh encoding format.
- Added the Prithvi mesh-adjacency residual coder as MO3D format v2, while retaining v1 baseline decoding.
- Added vertex position quantization and delta/varint triangle-index encoding.
- Added a deterministic synthetic-fixture generator and initial baseline measurements.
- Added unit tests and GitHub Actions workflows for cross-version tests and benchmark runs.
- Documented limitations and fair-comparison requirements. No claim is made that the prototype beats Draco or LZ4.
