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

The MO3D v1 experimental codec stores:

- XYZ coordinates quantized to a configurable precision of 8–24 bits per coordinate.
- Triangle connectivity encoded with delta indices and unsigned varints.
- zlib-compressed coordinate and face streams.

**Important limitation:** this first codec is lossy in position and geometry-only. It preserves triangle index connectivity, but drops normals, UV coordinates, colors, textures, materials, and source-format metadata. It is deliberately simple so we can test a measurable baseline before attempting a better predictor, topology coding, or learned representation. Do not use it as a replacement for production CAD, engineering, or archival data.

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
python -m middleout3d encode samples/icosphere.obj --out results/icosphere.mo3d --bits 16

# Decode to a standard mesh file
python -m middleout3d decode results/icosphere.mo3d --out results/icosphere-restored.obj

# Run unit tests
python -m unittest discover -s tests -v
```

Supported mesh input formats depend on trimesh; starter fixtures are OBJ. The decode command supports OBJ, PLY, STL, and OFF output.

## How to read the benchmark

- `gzip_lossless_bytes`: gzip result for the original file bytes, including original formatting and any attributes in that file.
- `mo3d_lossy_geometry_bytes`: custom prototype size containing only geometry and triangle topology.
- `mo3d_source_to_encoded_ratio`: included as a rough exploratory signal only; **it is not a fair codec comparison**, because MO3D is lossy and drops attributes.
- `geometry_max_vertex_error` / `geometry_rmse_vertex_distance`: distortion between corresponding source vertices and reconstructed vertices.
- `topology_exact`: verifies triangle index connectivity is unchanged.

The benchmark uses repeated runs and reports median wall-clock time. Timing is sensitive to CPU, Python, cache state, input size and system load. Do not compare numbers from different machines as if they were a controlled experiment.

## GitHub Actions

- **Tests** run on pushes, pull requests, and manual dispatch across Python 3.10, 3.12, and 3.13. The workflow runs unit tests and CLI encode/decode smoke tests.
- **Benchmark sample meshes** is manually triggered from the Actions tab. It accepts position-bit and repeat-count inputs and uploads JSON/CSV results as an artifact.

## Research roadmap

1. Establish stable baseline data and test correctness.
2. Add a Draco baseline with matched geometry precision and preserved attributes where supported.
3. Separate lossless mesh/attribute compression from lossy geometric quantization.
4. Investigate predictors for vertex positions, local coordinate frames, face-index entropy coding, and file/model-specific structure.
5. Evaluate point clouds and repeated CAD assemblies after mesh benchmarks are trustworthy.
6. Explore neural representations only with fixed distortion targets and full accounting for model weights, per-model codes, encode time, decode time, and decoder size.

## What would count as a win?

A published result must compare equivalent payloads and attribute sets, with the same reconstruction-quality constraint, on the same hardware. Report compression ratio, encode/decode throughput, peak memory where practical, error metrics, and all test files. An algorithm that wins only on our synthetic fixture should be described as a workload-specific result, not a general breakthrough.

## Security and correctness

MO3D v1 is experimental. Its decoder validates headers, stream lengths, coordinate counts, and triangle indices, but this has not been audited for hostile input or production use. Do not decode untrusted files in a privileged workflow.

## First measured baseline

See [`BASELINE_RESULTS.md`](BASELINE_RESULTS.md) and the machine-readable [`results/baseline.json`](results/baseline.json) / [`results/baseline.csv`](results/baseline.csv). The initial synthetic-fixture run is mixed: MO3D v1 improves file size versus a simple quantized-position + zlib/fixed-width-index reference on some fixtures but loses on others. This is the expected starting point for controlled experiments, not evidence of a universal compression breakthrough.
