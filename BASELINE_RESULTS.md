# MO3D Baseline vs Prithvi: First Hosted Experiment

**Run date:** 25 October 2026  
**Environment:** GitHub Actions `ubuntu-latest`, Python 3.12  
**Configuration:** 16 position bits per axis; median of 5 encode/decode runs; six deterministic synthetic meshes.  
**Run:** [GitHub Actions benchmark](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40148442164)  
**Snapshot:** [JSON](results/prithvi_ci_2026-10-25.json) · [CSV](results/prithvi_ci_2026-10-25.csv)

## Summary

At the same quantization precision, MO3D v2 Prithvi used **47,274 bytes** over the six separate encoded files versus **61,794 bytes** for the MO3D v1 absolute-coordinate baseline: **23.4974% fewer aggregate bytes** across this specific fixture set. Prithvi was smaller on four meshes and larger on two.

Both decoders reconstructed exactly the same quantized vertex coordinates, and all six preserved triangle indices exactly. Thus, the position error was unchanged by the predictor; geometric loss comes from the shared 16-bit quantization.

This is an initial synthetic-data result, not evidence of superiority over Draco, LZ4, or production compression systems.

## Per-mesh results

| Fixture | Baseline bytes | Prithvi bytes | Size reduction vs baseline | Baseline encode / decode (ms) | Prithvi encode / decode (ms) | Topology exact | Max vertex error |
|---|---:|---:|---:|---:|---:|:---:|---:|
| `box.obj` | 492 | 593 | -20.5285% | 0.0576 / 0.0414 | 0.1256 / 0.0734 | Yes | 0 |
| `cylinder.obj` | 1,061 | 1,078 | -1.6023% | 0.3117 / 0.1757 | 0.4937 / 0.4022 | Yes | 1.0790e-05 |
| `icosphere.obj` | 30,364 | 29,499 | 2.8488% | 7.4798 / 4.9114 | 11.4538 / 10.4092 | Yes | 2.4098e-05 |
| `torus.obj` | 3,789 | 3,611 | 4.6978% | 2.0227 / 1.2499 | 3.3170 / 3.0617 | Yes | 2.7370e-05 |
| `uv_sphere.obj` | 8,311 | 7,226 | 13.0550% | 4.2355 / 2.6924 | 6.7227 / 6.4531 | Yes | 2.5155e-05 |
| `wavy_grid.obj` | 17,777 | 5,267 | 70.3718% | 8.0416 / 5.0642 | 12.7377 / 12.2156 | Yes | 2.1238e-05 |

Negative size reduction means Prithvi produced a larger file. Wall-clock measurements are from a shared hosted runner and should be treated as indicative, not universal performance numbers.

## How to interpret it

- The strongest win in this set is `wavy_grid.obj` at **70.3718% smaller**. Its row-major vertex order makes adjacent vertices locally structured, which is exactly the kind of data this predictor may exploit.
- The box and cylinder fixtures became slightly larger. The predictor is not a universal win: its usefulness depends on the mesh topology, vertex ordering, residual distribution, and stream overhead.
- **Prithvi was slower than the baseline on all six fixtures** in this Python implementation. It has additional parent construction and residual-varint work; the current priority is to understand this cost and optimize it without changing the bitstream.
- The two coordinate coders use the same quantized coordinates. The baseline is MO3D format v1, while the predictive residual coder is format v2 so a v1 decoder cannot misread residuals as absolute coordinates.
- These meshes are generated synthetic fixtures. They do not establish behavior on real scans, CAD assemblies, robotics assets, or arbitrary triangulations.
- No head-to-head comparison with Google Draco or LZ4 has been run yet.

## Mathematical idea

For quantized integer vertex coordinate (Q_i\), the Prithvi encoder chooses the greatest adjacent vertex index below (i\), denoted (p(i)\). If one exists, it predicts (\widehat{Q}_i=Q_{p(i)}\); otherwise it predicts zero. It stores the signed residual (r_i=Q_i-\widehat{Q}_i\), zigzag maps it to a non-negative integer, encodes it as a varint, and compresses the stream with zlib. The decoder reconstructs in index order with (Q_i=\widehat{Q}_i+r_i\). The parent rule is deterministic from triangle connectivity, so a separate parent list is unnecessary.

The “Prithvi” name is a modern analogy to Atharvaveda 12.1’s descriptions of varied terrain supported by Earth; it is not a claim that the ancient text contains this compression algorithm.

## Reproduce

```bash
python -m middleout3d generate-fixtures --out samples
python -m middleout3d benchmark samples --out results/baseline.json --bits 16 --repeats 5
```

The benchmark command evaluates both baseline and Prithvi methods and emits JSON/CSV output. To encode with the predictor:

```bash
python -m middleout3d encode samples/wavy_grid.obj --out results/wavy-grid-prithvi.mo3d --bits 16 --method prithvi
python -m middleout3d decode results/wavy-grid-prithvi.mo3d --out results/wavy-grid-prithvi-decoded.obj
```

## Next experiments

1. Test alternative vertex orderings (source order, breadth-first traversal, spatial Morton order with explicit face-index remapping).
2. Optimize the predictor and varint path; track the speed/size trade-off.
3. Add public real-world CAD, scan, and robotics meshes where licensing permits redistribution.
4. Compare with Draco at matched precision/distortion and comparable attribute sets.
5. Sweep quantization precision and plot size against geometric error.
