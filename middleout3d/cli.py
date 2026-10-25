from __future__ import annotations
import argparse
import json

from .benchmark import benchmark_directory
from .connectivity_benchmark import benchmark_connectivity_directory
from .codec import FACE_ORDERINGS, ORDERINGS, decode_file, encode_file
from .fixtures import generate_fixtures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="middleout3d", description="Experimental 3D mesh compression and benchmark harness")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate-fixtures", help="create deterministic sample meshes")
    gen.add_argument("--out", default="samples", help="output directory")
    enc = sub.add_parser("encode", help="encode a mesh to the experimental .mo3d format")
    enc.add_argument("input")
    enc.add_argument("--out", required=True)
    enc.add_argument("--bits", type=int, default=16, help="position quantization bits (8-24); lower is smaller but less accurate")
    enc.add_argument("--method", choices=["baseline", "prithvi", "tangent", "weighted_tangent", "normal_fine_tangent", "chandas_tangent", "chandas_adaptive_tangent", "auto"], default="baseline", help="coder: baseline, Prithvi, tangent predictors, Chandas sparse-pattern or adaptive Chandas tangent coder, or size-optimized auto selection")
    enc.add_argument("--ordering", choices=list(ORDERINGS), default="source", help="vertex ordering: source, breadth-first mesh traversal (bfs), or spatial Morton ordering (morton)")
    enc.add_argument("--face-ordering", choices=list(FACE_ORDERINGS), default="source", help="triangle stream order: source face order or BFS over face adjacency with delta-cost cyclic rotation")
    enc.add_argument("--normal-step-ratio", type=float, default=0.5, help="MO3D v5 only: normal residual step relative to the equal-step budget (0<ratio<=1; smaller means finer normal precision)")
    dec = sub.add_parser("decode", help="decode a .mo3d file to OBJ, PLY, STL or OFF")
    dec.add_argument("input")
    dec.add_argument("--out", required=True)
    bench = sub.add_parser("benchmark", help="compare baseline, Prithvi, tangent variants including fixed, adaptive, and segmented Chandas, auto-selection, and Google Draco under source, BFS, and Morton vertex orderings")
    bench.add_argument("input_dir", nargs="?", default="samples")
    bench.add_argument("--out", default="results/baseline.json")
    bench.add_argument("--bits", type=int, default=16)
    bench.add_argument("--repeats", type=int, default=3)
    conn = sub.add_parser("benchmark-connectivity", help="compare source, greedy rotation, DP rotation, and BFS face ordering while preserving triangle winding")
    conn.add_argument("input_dir", nargs="?", default="samples")
    conn.add_argument("--out", default="results/connectivity-benchmark.json")
    conn.add_argument("--bits", type=int, default=16)
    conn.add_argument("--repeats", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate-fixtures":
            files = generate_fixtures(args.out)
            print(json.dumps({"generated": [str(p) for p in files]}, indent=2))
        elif args.command == "encode":
            print(json.dumps(encode_file(args.input, args.out, args.bits, method=args.method, ordering=args.ordering, normal_step_ratio=args.normal_step_ratio), indent=2))
        elif args.command == "decode":
            print(json.dumps(decode_file(args.input, args.out), indent=2))
        elif args.command == "benchmark":
            print(json.dumps(benchmark_directory(args.input_dir, args.out, args.bits, args.repeats), indent=2))
        elif args.command == "benchmark-connectivity":
            print(json.dumps(benchmark_connectivity_directory(args.input_dir, args.out, args.bits, args.repeats), indent=2))
        return 0
    except Exception as exc:
        print(f"middleout3d: error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
