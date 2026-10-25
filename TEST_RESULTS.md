# Local validation report

Date: 2026-10-25 (runtime date). Environment: Python 3.13.5, Linux x86_64, NumPy 2.3.5, Trimesh available in the test environment.

## Test suite

Command:

```bash
python -m unittest discover -s tests -v
```

Result from the local prototype validation: **5 tests passed**.

## Precision/topology sweep

The local validation loop tested all six generated OBJ fixtures at 8, 12, 16, 20, and 24 position bits (30 fixture/precision combinations).

- All 30 round trips decoded.
- Triangle face connectivity was exact in all 30 cases.
- Reconstructed coordinate errors stayed within the codec's per-axis quantization error bound in all 30 cases.
- Additional invalid-input checks rejected out-of-range indices, NaN positions, and fractional face indices.

## CLI smoke test

These commands succeeded locally on the generated `samples/icosphere.obj`:

```bash
python -m middleout3d encode samples/icosphere.obj --out /tmp/icosphere.mo3d --bits 16
python -m middleout3d decode /tmp/icosphere.mo3d --out /tmp/icosphere-restored.obj
```

In that run, source and decoded meshes each contained 2,562 vertices and 5,120 faces; face connectivity was identical. At 16 bits, the resulting MO3D file was 30,265 bytes. The decoded coordinates differed from the source by a maximum absolute component difference of approximately `1.526e-05` in that test.

## Repeat benchmark

A five-repeat benchmark of six synthetic fixtures completed with zero benchmark errors in the local run. See [BASELINE_RESULTS.md](BASELINE_RESULTS.md) for the summary.

## Not established

- No comparison against Draco has been performed yet.
- No claim is made that MO3D beats LZ4, Draco, or any production codec.
- Results use synthetic fixtures rather than a representative public CAD/robotics dataset.
- The current format is lossy in vertex positions and drops normals, UVs, colors, textures and materials.
- The decoder has not been security-audited for hostile files.

These results describe the earlier local working copy. CI must run to confirm the repository copy on its own environment.
