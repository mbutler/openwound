"""Checksum checks. These tests do not download the checkpoint."""

from pathlib import Path

import pytest

from ncm_art.model_adapter.artifacts import sha256_file, verify_file
from ncm_art.model_adapter.errors import AdapterError


def test_verify_file_accepts_a_matching_digest(tmp_path: Path):
    path = tmp_path / "sample.bin"
    path.write_bytes(b"openwound")
    digest = sha256_file(path)
    assert verify_file(path, len(b"openwound"), digest) == digest
    assert verify_file(path, len(b"openwound"), None) == digest


def test_verify_file_rejects_a_bad_size_or_digest(tmp_path: Path):
    path = tmp_path / "sample.bin"
    path.write_bytes(b"openwound")
    with pytest.raises(AdapterError) as size:
        verify_file(path, 3, None)
    assert size.value.code == "MODEL_NOT_READY"
    with pytest.raises(AdapterError) as digest:
        verify_file(path, len(b"openwound"), "0" * 64)
    assert digest.value.details["path"] == "sample.bin"
