"""Put the pinned NCM checkout on the import path, and nowhere else.

Upstream modules use generic names such as ``models`` and ``utils``. Those
imports must resolve inside ``vendor/ncm``.
"""

from pathlib import Path
import sys

from ncm_art.model_adapter.errors import AdapterError


def vendor_ncm_root() -> Path:
    return Path(__file__).resolve().parents[3] / "vendor" / "ncm"


def ensure_vendor_imports() -> Path:
    root = vendor_ncm_root()
    if not (root / "models" / "vqvae.py").is_file():
        raise AdapterError(
            "MODEL_NOT_READY",
            f"Pinned NCM source is missing at {root}.",
        )
    root_text = str(root)
    for name in ("models", "utils", "tokenization"):
        existing = sys.modules.get(name)
        origin = getattr(existing, "__file__", None) if existing is not None else None
        if origin is not None and not str(origin).startswith(root_text + "/"):
            raise AdapterError(
                "MODEL_NOT_READY",
                f"Refusing to use {name} imported from {origin}.",
                {"expected_root": root_text},
            )
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root
