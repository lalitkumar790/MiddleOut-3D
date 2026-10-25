# Vertex ordering study: source vs BFS vs Morton

**Run date:** 25 October 2026  
**Configuration:** 16 position bits per axis, five repetitions per operation, six deterministic synthetic OBJ meshes.  
**Workflow:** [Successful ordering benchmark](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40168239993)  
**Results:** [JSON](results/vertex_ordering_study_2026-10-25.json) · [CSV](results/vertex_ordering_study_2026-10-25.csv)

## Aggregate results

The sums below include all six geometry-only encoded files. The most meaningful codec ablation is Prithvi versus the baseline *within the same ordering*.

| Vertex ordering | Baseline total | Prithvi total | Prithvi size reduction vs same-order baseline | Baseline reduction vs source-order baseline |
|---|---:|---:|---:|---:|
| Source order | 61,956 B | 47,436 B | 23.4360% | 0.0000% |
| **BFS** | **49,634 B** | **36,345 B** | **26.7740%** | **19.8883%** |
| Morton | 79,687 B | 69,734 B | 12.4901% | -28.6187% |

The best tested configuration here is **BFS + Prithvi**. Its 36,345-byte total is 41.3374% smaller than the source-order absolute-coordinate baseline total. That is a combined effect of traversal order and the residual coder, so it should not be attributed to Prithvi alone.

## What changed per fixture?

| Fixture | Source baseline / Prithvi | BFS baseline / Prithvi | Morton baseline / Prithvi |
|---|---:|---:|---:|
| \`box.obj\` | 519 / 620 B | 514 / 615 B | 521 / 623 B |
| \`cylinder.obj\` | 1,088 / 1,105 B | 1,094 / 1,074 B | 1,139 / 1,134 B |
| \`icosphere.obj\` | 30,391 / 29,526 B | 14,554 / 13,522 B | 23,231 / 22,477 B |
| \`torus.obj\` | 3,816 / 3,638 B | 5,008 / 4,876 B | 7,167 / 6,680 B |
| \`uv_sphere.obj\` | 8,338 / 7,253 B | 8,295 / 5,498 B | 14,401 / 13,676 B |
| \`wavy_grid.obj\` | 17,804 / 5,294 B | 20,169 / 10,760 B | 33,228 / 25,144 B |

Prithvi is smaller than the same-order baseline on four of six meshes with source order, five of six with BFS, and five of six with Morton. The box is worse under all three orderings. Morton's total byte size is substantially worse than source order on this particular fixture collection.

## Interpretation

- **BFS improved aggregate size.** BFS starts each connected component from the lowest unseen input index and walks neighbors in ascending order. This changes both coordinate byte patterns and face-index patterns. It substantially improved the icosphere result and the UV sphere result in this test.
- **Morton did not win here.** It sorts vertices spatially using a 3D Morton/Z-order key, but spatial locality alone did not make the encoded coordinate plus face streams smaller for these fixtures.
- **Prithvi is still a size/speed trade-off.** The predictor saved bytes on many fixtures, but measured encoding and decoding were slower than the same-order baseline across this run. BFS ordering also adds preprocessing work, especially on larger meshes.
- **Correctness checks passed.** All 18 (six meshes × three orderings) baseline/Prithvi ordering combinations preserved face topology after mapping decoded indices back to the source order. At each ordering, baseline and Prithvi reconstructed the same quantized vertex coordinates.
- **This is not a production-codec comparison.** The fixtures are deterministic synthetic meshes, measurements ran on a shared hosted runner, and the current format omits normals, UVs, colors, textures, materials, and source metadata. No comparison with Draco or LZ4 is included.

## Next experiments

1. Keep BFS as an optional strategy, not the default, until it is tested on real CAD/robotics/scan datasets.
2. Reduce Python overhead in BFS adjacency construction, parent calculation, and residual coding; keep size and speed metrics separate.
3. Test alternative BFS roots and neighbor ordering, including degree-aware visitation, without tuning against only these six fixtures.
4. Evaluate orderings on a license-cleared real-world dataset and compare against Draco at matched distortion and attribute sets.

---

# MO3D Baseline vs Prithvi: First Hosted Experiment

**Run date:** 25 October 2026  
**Environment:** GitHub Actions `ubuntu-latest`, Python 3.12  
**Configuration:** 16 position bits per axis; median of 5 encode/decode runs; six deterministic synthetic meshes.  
**Run:** [GitHub Actions benchmark](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40148648174)  
**Snapshot:** [JSON](results/prithvi_ci_2026-10-25.json) · [CSV](results/prithvi_ci_2026-10-25.csv)

## Summary

At the same quantization precision, MO3D v2 Prithvi used **47,274 bytes** over the six separate encoded files versus **61,794 bytes** for the MO3D v1 absolute-coordinate baseline: **23.4974% fewer aggregate bytes** across this specific fixture set. Prithvi was smaller on four meshes and larger on two.

Both decoders reconstructed exactly the same quantized vertex coordinates, and all six preserved triangle indices exactly. Thus, the position error was unchanged by the predictor; geometric loss comes from the shared 16-bit quantization.

This is an initial synthetic-data result, not evidence of superiority over Draco, LZ4, or production compression systems.

## Per-mesh results

| Fixture | Baseline bytes | Prithvi bytes | Size reduction vs baseline | Baseline encode / decode (ms) | Prithvi encode / decode (ms) | Topology exact | Max vertex error |
|---|---:|---:|---:|---:|---:|:---:|---:|
| `box.obj` | 492 | 593 | -20.5285% | 0.0709 / 0.0510 | 0.1666 / 0.0861 | Yes | 0 |
| `cylinder.obj` | 1,061 | 1,078 | -1.6023% | 0.3806 / 0.1955 | 0.6265 / 0.4528 | Yes | 1.0790e-05 |
| `icosphere.obj` | 30,364 | 29,499 | 2.8488% | 10.1322 / 5.2191 | 15.6397 / 12.2187 | Yes | 2.4098e-05 |
| `torus.obj` | 3,789 | 3,611 | 4.6978% | 2.6955 / 1.3539 | 4.3751 / 3.6311 | Yes | 2.7370e-05 |
| `uv_sphere.obj` | 8,311 | 7,226 | 13.0550% | 5.7345 / 2.8872 | 8.9796 / 7.8309 | Yes | 2.5155e-05 |
| `wavy_grid.obj` | 17,777 | 5,267 | 70.3718% | 11.1803 / 5.2405 | 17.2841 / 14.1876 | Yes | 2.1238e-05 |

Negative size reduction means Prithvi produced a larger file. Wall-clock measurements are from a shared hosted runner and should be treated as indicative, not universal performance numbers.

## How to interpret it

- The strongest win in this set is `wavy_grid.obj` at **70.3718% smaller**. Its row-major vertex order makes adjacent vertices locally structured, which is exactly the kind of data this predictor may exploit.
- The box and cylinder fixtures became slightly larger. The predictor is not a universal win: its usefulness depends on the mesh topology, vertex ordering, residual distribution, and stream overhead.
- **Prithvi was slower than the baseline on all six fixtures** in this Python implementation. It has additional parent construction and residual-varint work; the current priority is to understand this cost and optimize it without changing the bitstream.
- The two coordinate coders use the same quantized coordinates. The baseline is MO3D format v1, while the predictive residual coder is format v2 so a v1 decoder cannot misread residuals as absolute coordinates.
- These meshes are generated synthetic fixtures. They do not establish behavior on real scans, CAD assemblies, robotics assets, or arbitrary triangulations.
- No head-to-head comparison with Google Draco or LZ4 has been run yet.

## Mathematical idea

For quantized integer vertex coordinate `Q_i`, the Prithvi encoder chooses the greatest adjacent vertex index below `i`, denoted `p(i)`. If one exists, it predicts `Q_hat_i = Q_{p(i)}`; otherwise it predicts zero. It stores the signed residual `r_i = Q_i - Q_hat_i`, maps signed values to non-negative integers with zigzag coding, encodes them as varints, and compresses the stream with zlib. The decoder reconstructs in index order with `Q_i = Q_hat_i + r_i`. The parent rule is deterministic from triangle connectivity, so a separate parent list is unnecessary.

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
