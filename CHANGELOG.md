# Changelog

## 0.1.0 — Initial research prototype

- Added the experimental MO3D v1 geometry-only mesh encoding format.
- Added the Prithvi mesh-adjacency residual coder as MO3D format v2, while retaining v1 baseline decoding.
- Added vertex position quantization and delta/varint triangle-index encoding.
- Added a CLI for fixture generation, encoding, decoding, and benchmarking.
- Added a deterministic synthetic-fixture generator and initial baseline measurements.
- Added unit tests and GitHub Actions workflows for cross-version tests and manual benchmark runs.
- Documented limitations and fair-comparison requirements. No claim is made that the prototype beats Draco or LZ4.
