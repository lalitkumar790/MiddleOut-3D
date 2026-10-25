"""MiddleOut-3D experimental 3D compression research prototype."""
__version__ = "0.1.0"
from .codec import CodecError, decode_mesh, encode_mesh
__all__ = ["CodecError", "encode_mesh", "decode_mesh", "__version__"]
