# Changelog

## 0.1.0 — Initial research prototype

- Added the experimental MO3D v1 geometry-only mesh encoding format.
- Added vertex position quantization and delta/varint triangle-index encoding.
- Added a CLI for fixture generation, encoding, decoding, and benchmarking.
- Added a deterministic synthetic-fixture generator and initial baseline measurements.
- Added unit tests and GitHub Actions workflows for cross-version tests and manual benchmark runs.
- Documented limitations and fair-comparison requirements. No claim is made that the prototype beats Draco or LZ4.
