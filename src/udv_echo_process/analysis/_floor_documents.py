"""Reading this pass's own published floor documents, authenticated against their tables.

WP3 and WP4 screen against floors another slice measured, so both read the pass's own WP1 and
WP2 documents beside the artefacts they are writing. Reading them is not adopting them — each
slice still compares them with what it recomputes from this pass's recordings — but a floor is
only evidence about *this* pass if the document and the table it was reduced from are the pair
the generating run published, and if the number a slice screens with is the number that table
itself carries. This module establishes both, once, so the two readers cannot drift apart.

Four facts are established, in this order, and each refusal names what failed:

* the document exists, is a JSON object, and states a named gate that passed;
* it names this pass's plan fingerprint;
* it publishes a ``table_sha256`` that equals the digest of the table beside it;
* the number a caller consumes is the number that authenticated table carries.

**Why the digest alone is not enough.** The digest ties the *document* to the *table*; it does
not tie the number written in the document to the number written in the table. A document whose
``spread.mean`` was edited keeps a valid ``table_sha256``, because the table did not move. So
each consumed floor is checked against its own row as well, and the two layers together are what
make the pair unusable apart: change the document and the table contradicts it, change the table
and the digest contradicts it.

**Why the digest is over the canonical form.** The generating slice writes LF and hashes what it
wrote, and git stores LF, while a Windows checkout with ``core.autocrlf=true`` materialises the
same file with CRLF. Hashing the working-tree bytes would turn a checkout's line endings into a
refusal, so the digest is taken over the LF form — the same rule the report's own test applies,
and the value ``git show HEAD:<path> | sha256sum`` yields.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

#: The digest a document publishes, and the prefix it carries it with.
DIGEST_ALGORITHM = "sha256"
DIGEST_PREFIX = f"{DIGEST_ALGORITHM}:"

#: The decimals the slices publish their floors at; comparisons happen there.
PUBLISHED_DECIMALS = 3

#: The quantity name the anchor table uses for a job's spread over its three anchors.
ANCHOR_SPREAD_QUANTITY = "anchor_range"


class FloorDocumentError(ValueError):
    """A published floor document that cannot be authenticated against its own table."""


class ReferenceEndpoints(NamedTuple):
    """The two endpoints, as the authenticated reference table carries them."""

    depth_resolved_value_mm_s: float
    depth_resolved_depth_mm: float
    depth_resolved_pair: tuple[str, str]
    depth_averaged_value_mm_s: float
    depth_averaged_pair: tuple[str, str]


def canonical_bytes(path: Path) -> bytes:
    """A table's canonical form: its bytes with CRLF line endings as LF."""
    return Path(path).read_bytes().replace(b"\r\n", b"\n")


def table_digest(path: Path) -> str:
    """The digest a document publishes for ``path``: over its canonical (LF) bytes."""
    return DIGEST_PREFIX + hashlib.sha256(canonical_bytes(path)).hexdigest()


def at_published_precision(value: float) -> float:
    """A floor at the precision the slices publish, where the two copies are compared."""
    return round(float(value), PUBLISHED_DECIMALS)


@dataclass(frozen=True)
class AuthenticatedFloor:
    """One floor document that passed every check, with the table it was verified against."""

    name: str
    slice_name: str
    path: Path
    document: Mapping[str, object]
    table_path: Path
    table_digest: str

    def _blocks(self) -> list[list[dict[str, str]]]:
        """The table's blocks, one per header: a document may publish more than one table."""
        blocks: list[list[dict[str, str]]] = []
        current: list[str] = []
        for line in canonical_bytes(self.table_path).decode("utf-8").splitlines():
            if line.strip():
                current.append(line)
            elif current:
                blocks.append(list(csv.DictReader(current)))
                current = []
        if current:
            blocks.append(list(csv.DictReader(current)))
        return blocks

    def _block_with(self, *columns: str) -> list[dict[str, str]]:
        """The one block whose header carries every named column."""
        for block in self._blocks():
            if block and set(columns) <= set(block[0]):
                return block
        raise FloorDocumentError(
            f"{self.slice_name}'s {self.name} publishes no table with the "
            f"{', '.join(repr(column) for column in columns)} column(s) in "
            f"{self.table_path.name}: the document's own number cannot be checked against a "
            "table that does not carry it"
        )

    def anchor_spread_mm_s(self, job: str, *, statistic: str) -> float:
        """The job's spread over its three anchors, as the authenticated table carries it."""
        rows = [
            row
            for row in self._block_with("job", "statistic", "quantity", "value")
            if row.get("job") == job
            and row.get("statistic") == statistic
            and row.get("quantity") == ANCHOR_SPREAD_QUANTITY
        ]
        where = (
            f"{self.table_path.name}: job {job!r}, statistic {statistic!r}, "
            f"quantity {ANCHOR_SPREAD_QUANTITY!r}"
        )
        if len(rows) != 1:
            raise FloorDocumentError(
                f"{self.slice_name}'s {self.name} carries {len(rows)} such rows in "
                f"{self.table_path.name}, expected exactly one ({where}): the document's "
                "number cannot be checked against a table that does not carry it"
            )
        return _tabulated_number(rows[0].get("value"), where=where)

    def reference_endpoints(self) -> ReferenceEndpoints:
        """Both reference endpoints, as the authenticated table's own pairs carry them.

        The two are the reductions WP2 defines: the largest absolute per-depth difference over
        the pairs, and the largest absolute difference between the pairs' depth-averaged means.
        """
        rows = self._block_with("left", "right")
        resolved = max(
            rows, key=lambda row: abs(_row_number(row, "max_abs_difference_mm_s"))
        )
        averaged = max(
            rows, key=lambda row: abs(_row_number(row, "mean_difference_mm_s"))
        )
        return ReferenceEndpoints(
            depth_resolved_value_mm_s=abs(
                _row_number(resolved, "max_abs_difference_mm_s")
            ),
            depth_resolved_depth_mm=_row_number(resolved, "max_abs_depth_mm"),
            depth_resolved_pair=(resolved["left"], resolved["right"]),
            depth_averaged_value_mm_s=abs(
                _row_number(averaged, "mean_difference_mm_s")
            ),
            depth_averaged_pair=(averaged["left"], averaged["right"]),
        )


def _row_number(row: Mapping[str, str], column: str) -> float:
    return _tabulated_number(row.get(column), where=column)


def _tabulated_number(value: object, *, where: str) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise FloorDocumentError(
            f"the authenticated table carries no number at {where} ({value!r})"
        ) from exc


def require_agrees(
    stated: float, tabulated: float, *, where: str, quantity: str
) -> None:
    """Refuse unless a document's published floor is the number its own table carries.

    Both copies are compared at the precision the slices publish, which is the precision the
    table itself states them at.
    """
    if at_published_precision(stated) != at_published_precision(tabulated):
        raise FloorDocumentError(
            f"{where} publishes {quantity} as {stated!r} but the authenticated table carries "
            f"{tabulated!r}: a floor is evidence only while the document and the table it was "
            "reduced from state the same number"
        )


def read_floor_document(
    directory: Path,
    name: str,
    *,
    slice_name: str,
    plan_fingerprint: str,
) -> AuthenticatedFloor:
    """One floor document, refused by name unless it is **this** pass's own and authenticated.

    Raises:
        FloorDocumentError: when the document is missing, unreadable, not a JSON object,
            carries no named gate or a failed one, belongs to another pass, publishes no
            table digest, has no table beside it, or publishes a digest its table does not
            hash to.
    """
    directory = Path(directory)
    path = directory / name
    if not path.is_file():
        raise FloorDocumentError(
            f"{slice_name}'s {name} is missing under {directory.as_posix()!r}: this slice "
            "screens each pass against that pass's own published floors, so it reads WP1's "
            "and WP2's documents beside this run's artefacts and never substitutes a number "
            "of its own"
        )
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FloorDocumentError(
            f"{slice_name}'s {name} is not a readable JSON document ({exc})"
        ) from exc
    if not isinstance(document, dict):
        raise FloorDocumentError(f"{slice_name}'s {name} is not a JSON object")
    checks = document.get("checks")
    failed = (
        sorted(key for key, ok in checks.items() if not ok)
        if isinstance(checks, dict)
        else []
    )
    if (
        not isinstance(checks, dict)
        or not checks
        or failed
        or document.get("ok") is not True
    ):
        raise FloorDocumentError(
            f"{slice_name}'s {name} did not pass its own gate (ok={document.get('ok')!r}, "
            f"failed={failed}): a floor published by a slice that did not hold is not "
            "evidence about anything"
        )
    fingerprint = document.get("plan_fingerprint")
    if fingerprint != plan_fingerprint:
        raise FloorDocumentError(
            f"{slice_name}'s {name} was measured for another pass (plan fingerprint "
            f"{fingerprint!r}, this pass's {plan_fingerprint!r}): the floors this slice "
            "screens with must be this pass's own"
        )
    stated = document.get("table_sha256")
    if not isinstance(stated, str) or not stated.startswith(DIGEST_PREFIX):
        raise FloorDocumentError(
            f"{slice_name}'s {name} publishes no table_sha256: the floor cannot be traced "
            "to the table it was reduced from"
        )
    table = path.with_suffix(".csv")
    if not table.is_file():
        raise FloorDocumentError(
            f"{slice_name}'s {name} has no {table.name} beside it under "
            f"{directory.as_posix()!r}: its published table_sha256 is the digest of that "
            "table, so a document without it cannot be authenticated"
        )
    actual = table_digest(table)
    if actual != stated:
        raise FloorDocumentError(
            f"{slice_name}'s {name} publishes table_sha256 {stated} but {table.name} hashes "
            f"to {actual}: the document and the table it was reduced from are not the pair "
            "the run that published them wrote, so the floor is refused rather than screened "
            "with"
        )
    return AuthenticatedFloor(
        name=name,
        slice_name=slice_name,
        path=path,
        document=document,
        table_path=table,
        table_digest=stated,
    )
