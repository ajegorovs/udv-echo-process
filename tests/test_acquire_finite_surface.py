"""The finite post-Run classifier has the same public identity at both entry points."""

from __future__ import annotations

from importlib import import_module

import pytest

from udv_echo_process.acquire import finite


@pytest.mark.parametrize("name", ["udv_echo_process", "udv_echo_process.acquire"])
def test_finite_exports_are_the_canonical_backend_objects(name: str) -> None:
    package = import_module(name)
    for exported in finite.__all__:
        assert exported in package.__all__
        assert getattr(package, exported) is getattr(finite, exported)
