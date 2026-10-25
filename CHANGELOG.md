# Changelog

## 0.3.0 — Non-uniform local-frame quantization experiment

- Added MO3D v5 `normal_fine_tangent`: a weighted tangent-space predictor with finer quantization along the local surface normal and coarser steps in the two tangential directions.
- Chose local residual steps so their squared step budget matches the equal-step tangent variant's theoretical Euclidean rounding-error bound.
- Added v5 stream magic and decoder support while retaining v1–v4 decoding.
- Expanded benchmark reports and adaptive selection to five in-house coders across source, BFS, and Morton ordering.
- Added tests for v5 header/signature compatibility, non-uniform step sizes, topology preservation and measured geometric-error bounds.
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
