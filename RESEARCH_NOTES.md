# Research notes: MiddleOut-3D and the Prithvi predictor

## Core hypothesis

A geometry-aware encoding can outperform generic byte compression on some 3D mesh datasets. The current hypothesis is narrower: a deterministic mesh-neighbor predictor may produce smaller residual streams than the prototype's absolute-coordinate representation on mesh families whose vertex ordering follows local geometry.

## Inspiration: Atharvaveda 12.1

Atharvaveda Book XII, Hymn 1 is commonly titled the Prithvi Sukta or Hymn to Earth. In Ralph T. H. Griffith's translation, verse 2 describes the Earth through heights, slopes, level plains, and plants with varied properties. See the [Wikisource edition](https://en.wikisource.org/wiki/Atharva-Veda_Samhita/Book_XII/Hymn_1) and [Griffith translation](https://original.sacred-texts.com/hin/av/av12001.htm).

The analogy is “one shared world supporting diverse local forms.” For a mesh, triangle connectivity describes local relationships; the codec uses one neighboring vertex to predict another, then stores only the residual.

This is a modern design inspiration only. We do not claim that the Vedic text gives, encodes, or historically anticipates the algorithm below.

## Prithvi algorithm (implemented)

Given a triangle mesh with vertices $x_i\in\mathbb{R}^3$ and faces $F$:

1. Quantize coordinates using the same axis-aligned bounds and $B$-bit grid as the baseline:
   $Q_i=\operatorname{round}(((x_i-b_{\min})/(b_{\max}-b_{\min}))(2^B-1))$.
2. Build the undirected adjacency implied by all triangle edges.
3. For vertex index $i$, choose its greatest earlier adjacent vertex: $p(i)=\max\{j< i\mid(i,j)\in E\}$. If no such vertex exists, use the zero vector.
4. Predict $\widehat Q_i=Q_{p(i)}$ and store the residual $r_i=Q_i-\widehat Q_i$.
5. Map signed residuals to non-negative integers by zigzag coding, encode each with unsigned varints, and zlib-compress the coordinate stream.
6. Store the same triangle-index stream used by the baseline, so a decoder can reconstruct the face graph and deterministically recompute each parent.

Because every parent has an index smaller than its child, decoding is causal: reconstruct $Q_i=\widehat Q_i+r_i$ in increasing vertex-index order. The residual representation is exact for the quantized integer grid. Geometry remains lossy only because of coordinate quantization.

## Evaluation questions

- Does Prithvi reduce coordinate-stream and total-file size versus the absolute-coordinate baseline at equal position precision?
- How does vertex ordering affect size? Current implementation uses source order and does not reorder vertices.
- Which mesh families benefit (grid-like surfaces, CAD parts, spheres, scans, irregular triangulations)?
- Is any improvement retained after accounting for the header, adjacency prediction costs, and decoder time?
- How does it compare with Google Draco when attributes, quantization and distortion constraints are matched?

## Failure modes and limitations

- Poor index order can make a vertex's chosen earlier neighbor geometrically distant, yielding large residuals.
- A varint+zlib residual stream may be larger than fixed-width quantized coordinates compressed by zlib.
- Triangle topology and vertex positions are preserved, but normals, UVs, colors, textures, materials, and source-file metadata are omitted.
- Synthetic fixtures do not establish broad performance claims.
- No claim is made that this codec beats Draco, LZ4, or any production codec.

## Next experiments

1. Run the automated baseline-versus-Prithvi comparison across all six built-in fixtures, 8–24 bit precision, and repeat counts.
2. Measure results for alternative vertex orderings: source order, breadth-first mesh traversal, and spatial Morton ordering (with explicit remapping of triangle indices).
3. Add a Draco baseline at comparable distortion and with the same attribute set.
4. Add surface-distance measures for topology-changing codecs.
5. Record CPU, OS, Python/dependency versions, encode/decode time, and peak memory.
6. Consider multi-parent prediction only after this simple causal predictor is measured and reproducible.
