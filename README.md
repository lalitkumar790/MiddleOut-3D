# MiddleOut-3D

**A Pied Piper-inspired research project for 3D geometry compression.** This is an experimental prototype—not a claim that it beats Draco, LZ4, or other established codecs.

The first milestone is a repeatable measurement pipeline. It includes a small geometry-only codec and reports size, encoding and decoding times, topology preservation, and positional error. It also compares gzip on the exact original file bytes, while clearly marking why that size comparison is not apples-to-apples.

## Why 3D data?

3D meshes contain both coordinates and connectivity. Regular mechanical geometry, smooth surfaces, repeated structures, and large collections of related models can have patterns that a specialized representation might exploit. But there is no universal compression ratio, and lossy neural geometry methods must be compared at equivalent reconstruction quality.

Relevant existing work:

- [Google Draco](https://github.com/google/draco) — established open-source compression for 3D meshes and point clouds.
- [MPEG G-PCC](https://www.mpeg.org/standards/MPEG-I/9/) — standardized geometry-based point-cloud compression.
- [Neural Compression for 3D Geometry Sets (ICCV 2025)](https://openaccess.thecvf.com/content/ICCV2025/html/Ren_Neural_Compression_for_3D_Geometry_Sets_ICCV_2025_paper.html) — neural compression for collections of 3D mesh models, reporting up to 900× in its studied setting. That result is for a specific representation and task, not a universal per-file promise.
- [Mesh Compression with Quantized Neural Displacement Fields (2025)](https://diglib.eg.org/items/d54ad053-5b75-49a3-91a4-1750449b7418) — neural displacement-field approach for lossy mesh compression.

## Current prototype

MO3D has two versioned coordinate coding methods:

- **MO3D v1 baseline:** per-axis quantized XYZ coordinates stored as fixed-width integers and compressed with zlib.
- **MO3D v2 Prithvi:** quantized coordinates encoded as signed residuals from a deterministic earlier mesh-neighbor, mapped to unsigned integers with zigzag coding, encoded as varints, then compressed with zlib.

The separate format version prevents an older v1 decoder from interpreting Prithvi residual bytes as absolute coordinates. The current decoder reads both v1 baseline and v2 Prithvi streams.

Both methods share the same quantizer, metadata and triangle-index stream. This makes the comparison useful for isolating the coordinate coder, though the total file still contains headers and zlib stream overhead.

**Important limitation:** both methods are lossy in position and geometry-only. They preserve triangle index connectivity and reconstructed quantized vertex positions, but drop normals, UV coordinates, colors, textures, materials, and source-format metadata. Do not use this experimental codec as a replacement for production CAD, engineering, or archival data.

## Prithvi: inspiration, not a historical claim

The name is a modern engineering analogy inspired by Atharvaveda 12.1, the *Prithvi Sukta*. Verse 2 describes Earth in terms of heights, slopes, plains, and plants with varied properties. The analogy we borrow is **one shared world supporting many different local forms**: let mesh connectivity predict nearby geometry so that the encoder stores differences, rather than every coordinate independently.

This does **not** imply that the Atharvaveda states or anticipates this mathematical compression algorithm. The predictor is a contemporary, falsifiable engineering hypothesis.

Reference translations: [Atharva-Veda Samhita, Book XII, Hymn 1 (Wikisource)](https://en.wikisource.org/wiki/Atharva-Veda_Samhita/Book_XII/Hymn_1) and [Ralph T. H. Griffith translation (Internet Sacred Text Archive)](https://original.sacred-texts.com/hin/av/av12001.htm).

### Mathematical design

Let original vertex coordinates be $x_i\in\mathbb{R}^3$, per-axis bounds be $b_{\min},b_{\max}$, and precision be $B$ bits. First quantize each coordinate to the integer grid:

\[
Q_i=\operatorname{round}\left(
\frac{x_i-b_{\min}}{b_{\max}-b_{\min}}(2^B-1)
\right)
\]

For constant axes, the normalized coordinate is set to zero. Faces define a mesh adjacency graph $G=(V,E)$. For vertex index $i$, choose the greatest adjacent index lower than $i$:

\[
p(i)=\max\{j\mid j<i,\ (i,j)\in E\}
\]

If no earlier neighbor exists, use the zero vector as the predictor; otherwise $\widehat Q_i=Q_{p(i)}$. The encoder stores the signed residual:

\[
r_i=Q_i-\widehat Q_i
\]

Each signed integer is mapped to a non-negative integer using zigzag coding ($2r$ for $r\ge0$, otherwise $-2r-1$), encoded as a variable-length integer, and compressed with zlib. Since $p(i)<i$, the decoder can reconstruct in vertex-index order:

\[
Q_i=\widehat Q_i+r_i
\]

The decoder recomputes parents from the face stream, so there is no separate parent table. The prediction stream is exact with respect to the quantized grid; the only geometric loss remains the original quantization step.

### Why this may help—and why it may fail

When a vertex's earlier adjacent neighbor is geometrically nearby, its residuals can have small magnitudes and require fewer varint bytes. But vertex ordering is crucial: non-local index assignments can yield large residuals, and the predictor may encode some meshes worse than the absolute baseline. zlib can also compress absolute integer streams efficiently. The benchmark therefore measures Prithvi **against the baseline at the same bit depth** instead of assuming it is better.

## Quick start

Python 3.10+ is recommended.

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt

# Generate reproducible OBJ fixtures without downloading anything
python -m middleout3d generate-fixtures --out samples

# Run the first benchmark; JSON and CSV reports are written
python -m middleout3d benchmark samples --out results/baseline.json --bits 16 --repeats 5

# Encode a mesh
python -m middleout3d encode samples/icosphere.obj --out results/icosphere.mo3d --bits 16 --method prithvi

# Decode to a standard mesh file
python -m middleout3d decode results/icosphere.mo3d --out results/icosphere-restored.obj

# Run unit tests
python -m unittest discover -s tests -v
```

Supported mesh input formats depend on trimesh; starter fixtures are OBJ. The decode command supports OBJ, PLY, STL, and OFF output.

## How to read the benchmark

- `gzip_lossless_bytes`: gzip result for the original file bytes, including original formatting and any attributes in that file.
- `mo3d_lossy_geometry_bytes`: absolute-coordinate baseline size containing only geometry and triangle topology.
- `prithvi_bytes` and `prithvi_size_reduction_vs_mo3d_baseline_pct`: predictor-coded size and size difference relative to the baseline at the same position precision.
- `prithvi_geometry_max_vertex_error`: maximum vertex-position error after decoding the Prithvi stream.
- `mo3d_source_to_encoded_ratio`: included as a rough exploratory signal only; **it is not a fair codec comparison**, because MO3D is lossy and drops attributes.
- `geometry_max_vertex_error` / `geometry_rmse_vertex_distance`: distortion between corresponding source vertices and reconstructed vertices.
- `topology_exact`: verifies triangle index connectivity is unchanged.

The benchmark uses repeated runs and reports median wall-clock time. Timing is sensitive to CPU, Python, cache state, input size and system load. Do not compare numbers from different machines as if they were a controlled experiment.

## GitHub Actions

- **Tests** run on pushes, pull requests, and manual dispatch across Python 3.10, 3.12, and 3.13. The workflow runs unit tests and CLI encode/decode smoke tests.
- **Benchmark sample meshes** runs on changes to the codec, tests or workflow, and can also be manually triggered from the Actions tab. It compares baseline vs Prithvi, prints per-mesh results, and uploads JSON/CSV reports. Manual dispatch accepts position-bit and repeat-count inputs.

## Research roadmap

1. Establish stable baseline data and test correctness.
2. Add a Draco baseline with matched geometry precision and preserved attributes where supported.
3. Evaluate Prithvi residual coding across multiple vertex orderings and mesh families; compare it against the absolute-coordinate baseline.
4. Add a Draco baseline with equivalent attributes and measured reconstruction error.
5. Separate lossless mesh/attribute compression from lossy geometric quantization.
6. Investigate stronger predictors, local coordinate frames, face-index entropy coding, and file/model-specific structure.
7. Evaluate point clouds and repeated CAD assemblies after mesh benchmarks are trustworthy.
8. Explore neural representations only with fixed distortion targets and full accounting for model weights, per-model codes, encode time, decode time, and decoder size.

## What would count as a win?

A published result must compare equivalent payloads and attribute sets, with the same reconstruction-quality constraint, on the same hardware. Report compression ratio, encode/decode throughput, peak memory where practical, error metrics, and all test files. An algorithm that wins only on our synthetic fixture should be described as a workload-specific result, not a general breakthrough.

## Security and correctness

MO3D v1 is experimental. Its decoder validates headers, stream lengths, coordinate counts, and triangle indices, but this has not been audited for hostile input or production use. Do not decode untrusted files in a privileged workflow.

## Measured baseline and Prithvi experiment

See [`BASELINE_RESULTS.md`](BASELINE_RESULTS.md) for the latest hosted baseline-versus-Prithvi comparison. The archived [Prithvi JSON report](results/prithvi_ci_2026-10-25.json) and [CSV report](results/prithvi_ci_2026-10-25.csv) record the six-fixture run. The earlier [initial baseline JSON](results/baseline.json) / [CSV](results/baseline.csv) remain as the pre-Prithvi exploratory snapshot.

The first Prithvi run reduced the sum of encoded bytes across six synthetic fixtures by 23.4974%, but it was smaller on only four of six meshes and slower than the baseline for every fixture. That is a workload-specific result, not evidence of a universal compression breakthrough. No comparison against Draco or LZ4 has been performed.
