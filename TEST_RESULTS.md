# Test and validation report

**Updated:** 25 October 2026

## Automated CI validation

- **Unit tests:** 9 tests passed on Python 3.10, 3.12, and 3.13 in the [GitHub Actions test run](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40148648166).
- **CLI smoke test:** the workflow generates sample meshes, encodes an OBJ file, and decodes the result.
- **Prithvi benchmark:** successful [baseline-vs-Prithvi benchmark run](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40148648174) on Python 3.12, with six synthetic fixtures and five timed repetitions per operation.

## What the tests cover

- Baseline encode/decode preserves triangle indices and stays within the quantization error bound.
- Higher coordinate precision does not worsen the tested reconstruction error.
- Prithvi reconstructed quantized vertex coordinates exactly match the absolute-coordinate baseline at the same precision.
- Both methods preserve triangle-index connectivity exactly on round-trip.
- Unsupported methods and bit depths are rejected.
- Corrupt bitstreams and mismatched format signatures/headers are rejected.
- A legacy MO3D v1 header without the newer optional coder metadata remains decodable.

## First Prithvi benchmark

At 16 bits per axis, the sum of encoded sizes across six deterministic synthetic fixtures was 61,794 bytes for the v1 absolute-coordinate baseline and 47,274 bytes for the v2 Prithvi method, an aggregate reduction of 23.4974%. Prithvi produced a smaller file on four fixtures and a larger file on two. Its encode/decode wall-clock medians were slower than the baseline for every fixture in the hosted Python run.

All six fixtures had exact topology reconstruction; baseline and Prithvi produced the same quantized vertex coordinates and therefore the same geometric error. The detailed table and interpretation are in [BASELINE_RESULTS.md](BASELINE_RESULTS.md), with machine-readable data in [JSON](results/prithvi_ci_2026-10-25.json) and [CSV](results/prithvi_ci_2026-10-25.csv).

## Not established

- No comparison with Google Draco or LZ4 has been performed.
- The benchmark fixtures are synthetic, not a representative CAD, scanning, point-cloud, or robotics dataset.
- The timing measurements come from a shared hosted runner and are not universal performance claims.
- Current format preserves XYZ geometry after quantization and triangle connectivity, but drops normals, UVs, colors, textures, materials, and other source-file metadata.
- The decoder has not been security-audited for hostile or arbitrarily large inputs.

These tests validate prototype correctness under the tested conditions; they do not establish production readiness or superiority to existing compression codecs.
