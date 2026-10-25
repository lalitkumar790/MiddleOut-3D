# Changelog

## 0.2.0 — Research-inspired predictors and codec comparison

- Added the MO3D v3 tangent-space residual coder using causal parallelogram prediction and a local orthonormal frame.
- Added the MO3D v4 valence-weighted tangent-space predictor, inspired by published weighted-parallelogram mesh compression research.
- Added size-first `--method auto`, which selects the shortest bitstream among four in-house coders and three vertex orderings.
- Added source, BFS and Morton vertex orderings with consistent face-index remapping.
- Expanded benchmark reports to include maximum vertex error, RMSE, encode/decode medians, topology checks and adaptive per-mesh selection.
- Added an optional `requirements-benchmark.txt` with DracoPy to compare the research codec with Google Draco using the same nominal quantization bit setting.
- Added CI checks for tangent/weighted-tangent geometry-error bounds and CLI smoke tests for weighted and adaptive encoders.
- Documented research sources, implementation limits and fair rate-distortion comparison requirements.

## 0.1.0 — Initial research prototype

- Added the experimental MO3D v1 geometry-only mesh encoding format.
- Added the Prithvi mesh-adjacency residual coder as MO3D format v2, while retaining v1 baseline decoding.
- Added vertex position quantization and delta/varint triangle-index encoding.
- Added a deterministic synthetic-fixture generator and initial baseline measurements.
- Added unit tests and GitHub Actions workflows for cross-version tests and benchmark runs.
- Documented limitations and fair-comparison requirements. No claim is made that the prototype beats Draco or LZ4.
