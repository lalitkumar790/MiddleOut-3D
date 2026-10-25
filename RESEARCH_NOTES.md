# Research notes and initial hypothesis

## Core hypothesis

A geometry-aware encoding can outperform generic byte compression on some 3D mesh datasets. It might also improve on established 3D codecs for a narrower workload, but this needs a controlled head-to-head evaluation.

## Why begin with quantized coordinates + topology?

This gives us a compact, testable baseline with measurable geometric error. Uniform bounding-box quantization is simple and not expected to be state of the art; it is the baseline we can improve. Triangle indices are represented with deltas and varints, then both streams are compressed.

## What is deliberately not claimed

- No claim of beating Draco or LZ4.
- No claim of lossless geometric reconstruction.
- No claim of preserving complete mesh assets: current version omits normals, UVs, colors, textures, materials, and other metadata.
- No inference from a synthetic benchmark alone to all real CAD/mesh data.
- Published neural compression ratios for collections of shapes are not directly comparable to per-file lossless compression.

## Candidate next experiments

1. Add a clean Draco baseline with matched quantization and geometry output.
2. Compare fixed precision settings (8, 10, 12, 14, 16, 20, 24 bits).
3. Use public datasets such as the Stanford 3D Scanning Repository, Thingi10K, and robotics/CAD assets that permit redistribution.
4. Add surface-distance metrics (e.g. symmetric Chamfer distance) for cases where a codec changes vertex ordering or topology.
5. Record CPU model, OS, Python/dependency versions, warmup, repeats, and peak memory.
6. Investigate coordinate prediction/residual coding before adding neural models.
