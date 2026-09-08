"""DOP-series (.BDD) reader sub-package.

Only the DOP3000/3010 family (`BINUDOPV` magic) is supported; `BINWDOPV`
(DOP2000) and 2-D/3-D UDVF modes are not (the repo's fixture files are
`BINUDOPV4.03.4`). A single reader is registered for the DOP-format source;
other vendors later get their own sub-package under ``io/``.
"""

from __future__ import annotations

from udv_echo_process.io.base import register_reader
from udv_echo_process.models.io import SourceFormat, SourceSpec

from . import bdd

DOP3000_SPEC = SourceSpec(
    vendor="Signal Processing SA",
    device="DOP 3010",
    format=SourceFormat.BDD,
)


def install() -> None:
    """Register the .BDD reader for the DOP-format source.

    Idempotent. Imported from `io/__init__.py` at package load so the reader
    is available without an explicit side-effecting import elsewhere.
    """
    register_reader(
        DOP3000_SPEC, bdd
    )  # register the reader *module* (has sniff + read)


install()
