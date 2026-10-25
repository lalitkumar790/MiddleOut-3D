"""Generate deterministic starter meshes without downloading a dataset."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import trimesh


def generate_fixtures(out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meshes = {
        "box.obj": trimesh.creation.box(extents=(1.0, 1.0, 1.0)),
        "icosphere.obj": trimesh.creation.icosphere(subdivisions=4, radius=1.0),
        "uv_sphere.obj": trimesh.creation.uv_sphere(radius=1.0, count=[40, 24]),
        "cylinder.obj": trimesh.creation.cylinder(radius=0.5, height=2.0, sections=48),
        "torus.obj": trimesh.creation.torus(major_radius=1.0, minor_radius=0.3, major_sections=48, minor_sections=18),
    }
    written = []
    for filename, mesh in meshes.items():
        path = out / filename
        mesh.export(path, file_type="obj")
        written.append(path)
    n = 60
    x = np.linspace(-1.0, 1.0, n)
    y = np.linspace(-1.0, 1.0, n)
    xx, yy = np.meshgrid(x, y)
    zz = 0.15 * np.sin(xx * 5.0) * np.cos(yy * 4.0)
    vertices = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
    faces = []
    for row in range(n - 1):
        for col in range(n - 1):
            a = row * n + col
            b = a + 1
            c = a + n
            d = c + 1
            faces.append([a, b, d])
            faces.append([a, d, c])
    grid = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces, dtype=np.int64), process=False)
    grid_path = out / "wavy_grid.obj"
    grid.export(grid_path, file_type="obj")
    written.append(grid_path)
    return written
