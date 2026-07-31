"""Local, fail-closed relay ledger for the R3 candidate.

The authoritative carrier is canonical UTF-8/LF NDJSON.  Ordering is per stream;
there is deliberately no cross-stream MAX+1 allocator.  The module provides local
integrity and crash reconciliation, not an external transparency anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


ENTRY_SCHEMA = "omni-relay-ledger-entry-v1"
LEASE_SCHEMA = "omni-relay-ledger-lease-v1"
LEASE_AUTHORITY_SCHEMA = "omni-relay-ledger-lease-authority-v1"
VOLUME_SEAL_SCHEMA = "omni-relay-ledger-volume-seal-v1"
CHECKPOINT_SCHEMA = "omni-relay-ledger-vector-checkpoint-v1"
TORN_PLAN_SCHEMA = "omni-relay-ledger-torn-tail-plan-v1"
REPAIR_AUTHORITY_SCHEMA = "omni-relay-ledger-repair-authority-v1"
REPAIR_RECEIPT_SCHEMA = "omni-relay-ledger-repair-receipt-v1"
EXTERNAL_ANCHOR_SCHEMA = "omni-relay-ledger-external-anchor-v1"
EXTERNAL_ANCHOR_QUALIFICATION_SCHEMA = (
    "omni-relay-ledger-external-anchor-qualification-v1"
)
EXTERNAL_ANCHOR_SUBJECT_SCHEMA = (
    "omni-relay-ledger-external-anchor-qualification-subject-v1"
)
ROTATION_POLICY_SCHEMA = "omni-relay-ledger-rotation-policy-v1"
INTEGRITY_SCOPE = "LOCAL_HASH_CHAIN_UNANCHORED"
EXTERNAL_ANCHOR_SCOPE = "EXTERNAL_CREATE_ONCE_VECTOR_HEAD_ANCHOR"
CANONICALIZATION_VERSION = "OMNI_CANONICAL_JSON_V1"
DEFAULT_MAX_ENTRIES_PER_VOLUME = 1_000
DEFAULT_MAX_BYTES_PER_VOLUME = 8_388_608
ROTATION_REASON_ORDER = (
    "ENTRY_THRESHOLD",
    "BYTE_THRESHOLD",
    "PHASE_GATE",
    "MANUAL_REQUEST",
)

ENTRY_DOMAIN = b"OMNI-RELAY-ENTRY-V1\0"
REQUEST_DOMAIN = b"OMNI-RELAY-REQUEST-V1\0"
LEASE_DOMAIN = b"OMNI-RELAY-LEASE-V1\0"
SEAL_DOMAIN = b"OMNI-RELAY-VOLUME-SEAL-V1\0"
CHECKPOINT_DOMAIN = b"OMNI-RELAY-CHECKPOINT-V1\0"
PLAN_DOMAIN = b"OMNI-RELAY-TORN-PLAN-V1\0"
AUTHORITY_DOMAIN = b"OMNI-RELAY-AUTHORITY-V1\0"
EXTERNAL_ANCHOR_DOMAIN = b"OMNI-RELAY-EXTERNAL-ANCHOR-V1\0"
EXTERNAL_ANCHOR_HEADS_DOMAIN = b"OMNI-RELAY-EXTERNAL-ANCHOR-HEADS-V1\0"
EXTERNAL_ANCHOR_QUALIFICATION_DOMAIN = (
    b"OMNI-RELAY-EXTERNAL-ANCHOR-QUALIFICATION-V1\0"
)

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[A-F0-9]{64}$")
EVENT_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
VOLUME_FILE = re.compile(r"^(?P<stream>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\.(?P<number>[0-9]{6})\.ndjson$")
LEASE_FILE = re.compile(r"^(?P<stream>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\.lease\.(?P<fence>[0-9]{20})\.json$")
EXTERNAL_ANCHOR_FILE = re.compile(
    r"^(?P<anchor>[A-Za-z0-9][A-Za-z0-9._-]{0,127})\.anchor\."
    r"(?P<sequence>[0-9]{20})\.json$"
)

ENTRY_FIELDS = frozenset(
    {
        "schema",
        "run_id",
        "stream_id",
        "volume_id",
        "volume_no",
        "stream_seq",
        "event_id",
        "writer_id",
        "writer_instance_id",
        "lease_id",
        "fence",
        "topology",
        "hat",
        "independent_verifier",
        "created_at",
        "kind",
        "title",
        "body",
        "body_bytes",
        "canonicalization_version",
        "observed_heads",
        "supersedes",
        "request_hash",
        "prev_entry_hash",
        "prev_volume_seal_hash",
        "integrity_scope",
        "entry_hash",
    }
)


class LedgerError(RuntimeError):
    """Typed, fail-closed ledger failure."""

    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}:{detail}")


@dataclass(frozen=True)
class RotationPolicy:
    """Per-stream limits applied under the physical writer lock."""

    max_entries_per_volume: int = DEFAULT_MAX_ENTRIES_PER_VOLUME
    max_bytes_per_volume: int = DEFAULT_MAX_BYTES_PER_VOLUME

    def __post_init__(self) -> None:
        for label, value in (
            ("max_entries_per_volume", self.max_entries_per_volume),
            ("max_bytes_per_volume", self.max_bytes_per_volume),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise LedgerError("ROTATION_POLICY_INVALID", label)

    def as_record(self) -> dict[str, Any]:
        return {
            "schema": ROTATION_POLICY_SCHEMA,
            "max_entries_per_volume": self.max_entries_per_volume,
            "max_bytes_per_volume": self.max_bytes_per_volume,
        }


@dataclass(frozen=True)
class Lease:
    writer_id: str
    writer_instance_id: str
    lease_id: str
    fence: int
    expires_at: str


def canonical_json(value: Any) -> str:
    """Canonical JSON for this integer/string/bool/null-only contract."""
    _reject_noncanonical_types(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_line(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8") + b"\n"


def _reject_noncanonical_types(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LedgerError("NONFINITE_NUMBER_FORBIDDEN", path)
        raise LedgerError("FLOAT_FORBIDDEN", path)
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_noncanonical_types(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise LedgerError("NONSTRING_KEY_FORBIDDEN", path)
            _reject_noncanonical_types(item, f"{path}.{key}")
        return
    raise LedgerError("JSON_TYPE_FORBIDDEN", f"{path}:{type(value).__name__}")


def strict_json(text: str) -> Any:
    if text.startswith("\ufeff"):
        raise LedgerError("JSON_BOM_FORBIDDEN")

    def reject_float(value: str) -> None:
        raise LedgerError("JSON_FLOAT_FORBIDDEN", value)

    def reject_constant(value: str) -> None:
        raise LedgerError("JSON_CONSTANT_FORBIDDEN", value)

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LedgerError("JSON_DUPLICATE_KEY", key)
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            parse_float=reject_float,
            parse_constant=reject_constant,
            object_pairs_hook=unique_pairs,
        )
    except LedgerError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LedgerError("JSON_MALFORMED", str(error)) from error


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def hash_core(domain: bytes, value: Mapping[str, Any]) -> str:
    return sha256_bytes(domain + canonical_json(dict(value)).encode("utf-8"))


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_time(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LedgerError("UTC_TIMESTAMP_REQUIRED", label)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise LedgerError("TIMESTAMP_INVALID", label) from error
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise LedgerError("UTC_TIMESTAMP_REQUIRED", label)
    return parsed


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise LedgerError("IDENTIFIER_INVALID", label)
    return value


def _event_id(value: str) -> str:
    if not isinstance(value, str) or EVENT_ID.fullmatch(value) is None:
        raise LedgerError("EVENT_ID_INVALID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError(value)
    except ValueError as error:
        raise LedgerError("EVENT_ID_INVALID") from error
    return value


def _hash(value: str | None, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise LedgerError("SHA256_INVALID", label)
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LedgerError("POSITIVE_INTEGER_REQUIRED", label)
    return value


def _normalize_text(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise LedgerError("TEXT_REQUIRED", label)
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _bounded_text(value: str, label: str, maximum: int) -> str:
    normalized = _normalize_text(value, label)
    if len(normalized) > maximum:
        raise LedgerError("TEXT_TOO_LARGE", label)
    return normalized


def _validate_observed_heads(value: Any) -> list[dict[str, Any]]:
    """Validate one sorted causal vector; never derive a total order from it."""
    if not isinstance(value, (list, tuple)):
        raise LedgerError("OBSERVED_HEADS_LIST_REQUIRED")
    heads: list[dict[str, Any]] = []
    streams: list[str] = []
    for index, candidate in enumerate(value):
        if not isinstance(candidate, Mapping) or set(candidate) != {
            "stream_id",
            "stream_seq",
            "entry_hash",
        }:
            raise LedgerError("OBSERVED_HEAD_MALFORMED", str(index))
        head = {
            "stream_id": candidate["stream_id"],
            "stream_seq": candidate["stream_seq"],
            "entry_hash": candidate["entry_hash"],
        }
        _safe_id(head["stream_id"], f"observed_heads[{index}].stream_id")
        _positive_int(head["stream_seq"], f"observed_heads[{index}].stream_seq")
        _hash(head["entry_hash"], f"observed_heads[{index}].entry_hash")
        streams.append(head["stream_id"])
        heads.append(head)
    if len(streams) != len(set(streams)):
        raise LedgerError("OBSERVED_HEAD_STREAM_DUPLICATE")
    if streams != sorted(streams):
        raise LedgerError("OBSERVED_HEADS_NOT_SORTED")
    return heads


def _validate_rotation_policy_record(value: Any) -> RotationPolicy:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "max_entries_per_volume",
        "max_bytes_per_volume",
    }:
        raise LedgerError("ROTATION_POLICY_MALFORMED")
    if value["schema"] != ROTATION_POLICY_SCHEMA:
        raise LedgerError("ROTATION_POLICY_SCHEMA_INVALID")
    return RotationPolicy(
        max_entries_per_volume=value["max_entries_per_volume"],
        max_bytes_per_volume=value["max_bytes_per_volume"],
    )


def _rotation_reasons(
    entry_count: int,
    byte_length: int,
    policy: RotationPolicy,
    *,
    phase_gate_id: str | None = None,
    manual_request: bool = False,
) -> list[str]:
    if isinstance(entry_count, bool) or not isinstance(entry_count, int) or entry_count < 1:
        raise LedgerError("ROTATION_ENTRY_COUNT_INVALID")
    if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length < 1:
        raise LedgerError("ROTATION_BYTE_LENGTH_INVALID")
    selected: set[str] = set()
    if entry_count >= policy.max_entries_per_volume:
        selected.add("ENTRY_THRESHOLD")
    if byte_length >= policy.max_bytes_per_volume:
        selected.add("BYTE_THRESHOLD")
    if phase_gate_id is not None:
        _safe_id(phase_gate_id, "phase_gate_id")
        selected.add("PHASE_GATE")
    if manual_request:
        selected.add("MANUAL_REQUEST")
    return [reason for reason in ROTATION_REASON_ORDER if reason in selected]


def _fsync_directory(directory: Path) -> None:
    """Best effort metadata flush; Windows may reject directory handles."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _path_fingerprint(path: Path) -> str:
    """Bind a physical path without publishing it in the anchor record."""
    physical = path.resolve(strict=True)
    normalized = os.path.normcase(os.path.normpath(str(physical)))
    return sha256_bytes(b"OMNI-RELAY-PATH-V1\0" + normalized.encode("utf-8"))


def _roots_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def _resolve_external_anchor_root(
    anchor_root: str | Path,
    ledgers: Sequence["RelayLedger"],
    *,
    create: bool,
) -> Path:
    candidate = Path(anchor_root).resolve(strict=False)
    for ledger in ledgers:
        ledger_root = ledger.root.resolve(strict=True)
        if _roots_overlap(candidate, ledger_root):
            raise LedgerError(
                "ANCHOR_ROOT_NOT_DISTINCT",
                f"{candidate}:{ledger_root}",
            )
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    elif not candidate.is_dir():
        raise LedgerError("ANCHOR_ROOT_MISSING", str(candidate))
    physical = candidate.resolve(strict=True)
    for ledger in ledgers:
        ledger_root = ledger.root.resolve(strict=True)
        if _roots_overlap(physical, ledger_root):
            raise LedgerError(
                "ANCHOR_ROOT_NOT_DISTINCT",
                f"{physical}:{ledger_root}",
            )
    return physical


def _read_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            data = handle.read()
            after = os.fstat(handle.fileno())
        observed = path.stat()
    except OSError as error:
        raise LedgerError("READ_FAILED", str(path)) from error
    if (
        not os.path.samestat(before, after)
        or not os.path.samestat(after, observed)
        or len(data) != after.st_size
    ):
        raise LedgerError("READ_IDENTITY_DRIFT", str(path))
    return data


def _decode_canonical_record(data: bytes, label: str) -> dict[str, Any]:
    if not data.endswith(b"\n") or data.count(b"\n") != 1:
        raise LedgerError("CANONICAL_SINGLE_LINE_REQUIRED", label)
    try:
        text = data[:-1].decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise LedgerError("UTF8_INVALID", label) from error
    value = strict_json(text)
    if not isinstance(value, dict):
        raise LedgerError("JSON_OBJECT_REQUIRED", label)
    if canonical_line(value) != data:
        raise LedgerError("NONCANONICAL_JSON", label)
    return value


def _create_once(path: Path, data: bytes) -> str:
    try:
        with path.open("xb") as handle:
            written = handle.write(data)
            if written != len(data):
                raise LedgerError("SHORT_WRITE", str(path))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
        status = "CREATED"
    except FileExistsError:
        status = "ALREADY_PRESENT"
    observed = _read_bytes(path)
    if observed != data:
        raise LedgerError("CREATE_ONCE_COLLISION", str(path))
    return status


def _atomic_replace(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.pending.", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            written = handle.write(data)
            if written != len(data):
                raise LedgerError("SHORT_WRITE", str(temporary))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        if _read_bytes(path) != data:
            raise LedgerError("ATOMIC_REPLACE_READBACK_MISMATCH", str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _exclusive_lock(path: Path, timeout: float = 5.0) -> Iterator[None]:
    """One-byte interprocess lock held across tail validation and readback."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b", buffering=0)
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + timeout
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if time.monotonic() >= deadline:
                        raise LedgerError("LOCK_TIMEOUT", str(path)) from error
                    time.sleep(0.025)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if time.monotonic() >= deadline:
                        raise LedgerError("LOCK_TIMEOUT", str(path)) from error
                    time.sleep(0.025)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class RelayLedger:
    """One per-agent stream with one active fenced physical writer."""

    def __init__(
        self,
        root: str | Path,
        run_id: str,
        stream_id: str,
        *,
        topology: str = "TEAM",
        independent_verifier: bool = False,
        rotation_policy: RotationPolicy | None = None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_id = _safe_id(run_id, "run_id")
        self.stream_id = _safe_id(stream_id, "stream_id")
        if topology not in {"TEAM", "SOLO_HATS"}:
            raise LedgerError("TOPOLOGY_INVALID")
        if not isinstance(independent_verifier, bool):
            raise LedgerError("INDEPENDENT_VERIFIER_BOOLEAN_REQUIRED")
        if topology == "SOLO_HATS" and independent_verifier:
            raise LedgerError("SOLO_INDEPENDENCE_FALSE_REQUIRED")
        self.topology = topology
        self.independent_verifier = independent_verifier
        if rotation_policy is not None and not isinstance(
            rotation_policy, RotationPolicy
        ):
            raise LedgerError("ROTATION_POLICY_TYPE_INVALID")
        self.rotation_policy = rotation_policy or RotationPolicy()
        self._lock_path = self.root / f".{self.stream_id}.relay.lock"

    def _volume_id(self, number: int) -> str:
        return f"{self.run_id}.{self.stream_id}.{number:06d}"

    def _volume_path(self, number: int) -> Path:
        return self.root / f"{self.stream_id}.{number:06d}.ndjson"

    def _seal_path(self, number: int) -> Path:
        return self.root / f"{self.stream_id}.{number:06d}.seal.json"

    def _lease_path(self, fence: int) -> Path:
        return self.root / f"{self.stream_id}.lease.{fence:020d}.json"

    def _repair_path(self, volume_no: int, authority_id: str, status: str) -> Path:
        return self.root / (
            f"{self.stream_id}.{volume_no:06d}.repair."
            f"{_safe_id(authority_id, 'authority_id')}.{status.lower()}.json"
        )

    def _discover_volumes(self) -> list[tuple[int, Path]]:
        result: list[tuple[int, Path]] = []
        for path in self.root.glob(f"{self.stream_id}.*.ndjson"):
            match = VOLUME_FILE.fullmatch(path.name)
            if match and match.group("stream") == self.stream_id:
                result.append((int(match.group("number")), path))
        result.sort()
        if result and [number for number, _ in result] != list(
            range(1, result[-1][0] + 1)
        ):
            raise LedgerError("VOLUME_SEQUENCE_GAP")
        return result

    def _load_leases_locked(self) -> list[dict[str, Any]]:
        paths: list[tuple[int, Path]] = []
        for path in self.root.glob(f"{self.stream_id}.lease.*.json"):
            match = LEASE_FILE.fullmatch(path.name)
            if match and match.group("stream") == self.stream_id:
                paths.append((int(match.group("fence")), path))
        paths.sort()
        records: list[dict[str, Any]] = []
        previous_hash: str | None = None
        previous_fence = 0
        for fence, path in paths:
            record = _decode_canonical_record(_read_bytes(path), str(path))
            required = {
                "schema",
                "run_id",
                "stream_id",
                "writer_id",
                "writer_instance_id",
                "lease_id",
                "fence",
                "expires_at",
                "topology",
                "independent_verifier",
                "activated_at",
                "authority_id",
                "authority_source",
                "authority_hash",
                "previous_lease_hash",
                "integrity_scope",
                "lease_hash",
            }
            if set(record) != required or record.get("schema") != LEASE_SCHEMA:
                raise LedgerError("LEASE_RECORD_MALFORMED", str(path))
            if (
                record["run_id"] != self.run_id
                or record["stream_id"] != self.stream_id
                or record["topology"] != self.topology
                or record["independent_verifier"] != self.independent_verifier
            ):
                raise LedgerError("LEASE_SCOPE_MISMATCH", str(path))
            if fence != record["fence"] or fence <= previous_fence:
                raise LedgerError("LEASE_FENCE_ORDER_INVALID", str(path))
            if record["previous_lease_hash"] != previous_hash:
                raise LedgerError("LEASE_CHAIN_BROKEN", str(path))
            for field in (
                "writer_id",
                "writer_instance_id",
                "lease_id",
                "authority_id",
            ):
                _safe_id(record[field], field)
            _positive_int(record["fence"], "fence")
            if record["authority_source"] not in {"HUMAN_EXPLICIT", "POLICY_BROKER"}:
                raise LedgerError("LEASE_AUTHORITY_SOURCE_INVALID")
            if record["integrity_scope"] != INTEGRITY_SCOPE:
                raise LedgerError("INTEGRITY_SCOPE_OVERCLAIM")
            core = dict(record)
            observed_hash = core.pop("lease_hash")
            if observed_hash != hash_core(LEASE_DOMAIN, core):
                raise LedgerError("LEASE_HASH_MISMATCH", str(path))
            _parse_time(record["expires_at"], "lease.expires_at")
            _parse_time(record["activated_at"], "lease.activated_at")
            _hash(record["authority_hash"], "authority_hash")
            _hash(record["lease_hash"], "lease_hash")
            _hash(
                record["previous_lease_hash"],
                "previous_lease_hash",
                nullable=True,
            )
            previous_hash = record["lease_hash"]
            previous_fence = fence
            records.append(record)
        return records

    def activate_lease(
        self, lease: Lease, authority: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Create one higher-fence lease receipt; authority is caller supplied."""
        self._validate_lease_input(lease)
        expected_authority_fields = {
            "schema",
            "action",
            "run_id",
            "stream_id",
            "writer_id",
            "writer_instance_id",
            "lease_id",
            "fence",
            "topology",
            "independent_verifier",
            "authorized_by",
            "authority_id",
            "authority_source",
            "authorized_at",
            "expires_at",
        }
        if set(authority) != expected_authority_fields:
            raise LedgerError("LEASE_AUTHORITY_MALFORMED")
        expected = {
            "schema": LEASE_AUTHORITY_SCHEMA,
            "action": "ACTIVATE_STREAM_LEASE",
            "run_id": self.run_id,
            "stream_id": self.stream_id,
            "writer_id": lease.writer_id,
            "writer_instance_id": lease.writer_instance_id,
            "lease_id": lease.lease_id,
            "fence": lease.fence,
            "topology": self.topology,
            "independent_verifier": self.independent_verifier,
        }
        for key, value in expected.items():
            if authority.get(key) != value:
                raise LedgerError("LEASE_AUTHORITY_BINDING_MISMATCH", key)
        _safe_id(authority["authorized_by"], "authorized_by")
        _safe_id(authority["authority_id"], "authority_id")
        if authority["authority_source"] not in {"HUMAN_EXPLICIT", "POLICY_BROKER"}:
            raise LedgerError("LEASE_AUTHORITY_SOURCE_INVALID")
        _parse_time(authority["authorized_at"], "authority.authorized_at")
        if _parse_time(authority["expires_at"], "authority.expires_at") <= datetime.now(
            timezone.utc
        ):
            raise LedgerError("LEASE_AUTHORITY_EXPIRED")

        with _exclusive_lock(self._lock_path):
            leases = self._load_leases_locked()
            current = leases[-1] if leases else None
            if current and lease.fence == current["fence"]:
                matching = all(
                    current[key] == getattr(lease, key)
                    for key in (
                        "writer_id",
                        "writer_instance_id",
                        "lease_id",
                        "fence",
                        "expires_at",
                    )
                )
                if matching:
                    return current
                raise LedgerError("LEASE_FENCE_COLLISION")
            if current and lease.fence <= current["fence"]:
                raise LedgerError("STALE_FENCE")
            authority_hash = hash_core(AUTHORITY_DOMAIN, dict(authority))
            core = {
                "schema": LEASE_SCHEMA,
                "run_id": self.run_id,
                "stream_id": self.stream_id,
                "writer_id": lease.writer_id,
                "writer_instance_id": lease.writer_instance_id,
                "lease_id": lease.lease_id,
                "fence": lease.fence,
                "expires_at": lease.expires_at,
                "topology": self.topology,
                "independent_verifier": self.independent_verifier,
                "activated_at": _now(),
                "authority_id": authority["authority_id"],
                "authority_source": authority["authority_source"],
                "authority_hash": authority_hash,
                "previous_lease_hash": current["lease_hash"] if current else None,
                "integrity_scope": INTEGRITY_SCOPE,
            }
            record = {**core, "lease_hash": hash_core(LEASE_DOMAIN, core)}
            _create_once(self._lease_path(lease.fence), canonical_line(record))
            observed = self._load_leases_locked()[-1]
            if observed != record:
                raise LedgerError("LEASE_READBACK_MISMATCH")
            return observed

    def _validate_lease_input(self, lease: Lease) -> None:
        _safe_id(lease.writer_id, "writer_id")
        _safe_id(lease.writer_instance_id, "writer_instance_id")
        _safe_id(lease.lease_id, "lease_id")
        _positive_int(lease.fence, "fence")
        _parse_time(lease.expires_at, "lease.expires_at")

    def _require_active_lease_locked(self, lease: Lease) -> dict[str, Any]:
        self._validate_lease_input(lease)
        leases = self._load_leases_locked()
        if not leases:
            raise LedgerError("LEASE_NOT_PROVISIONED")
        current = leases[-1]
        for key in (
            "writer_id",
            "writer_instance_id",
            "lease_id",
            "fence",
            "expires_at",
        ):
            if current[key] != getattr(lease, key):
                raise LedgerError("LEASE_MISMATCH", key)
        if _parse_time(current["expires_at"], "lease.expires_at") <= datetime.now(
            timezone.utc
        ):
            raise LedgerError("LEASE_EXPIRED")
        return current

    def _validate_entry_shape(self, record: dict[str, Any]) -> None:
        if set(record) != ENTRY_FIELDS or record.get("schema") != ENTRY_SCHEMA:
            raise LedgerError("ENTRY_SCHEMA_MALFORMED")
        for field in (
            "run_id",
            "stream_id",
            "writer_id",
            "writer_instance_id",
            "lease_id",
        ):
            _safe_id(record[field], field)
        _positive_int(record["volume_no"], "volume_no")
        _positive_int(record["stream_seq"], "stream_seq")
        _positive_int(record["fence"], "fence")
        _event_id(record["event_id"])
        _parse_time(record["created_at"], "created_at")
        if record["topology"] not in {"TEAM", "SOLO_HATS"}:
            raise LedgerError("TOPOLOGY_INVALID")
        if record["hat"] not in {"BUILDER", "VERIFIER", "OTHER"}:
            raise LedgerError("HAT_INVALID")
        if record["kind"] not in {"MESSAGE", "CORRECTION", "CONTROL"}:
            raise LedgerError("ENTRY_KIND_INVALID")
        if record["canonicalization_version"] != CANONICALIZATION_VERSION:
            raise LedgerError("CANONICALIZATION_VERSION_INVALID")
        if not isinstance(record["independent_verifier"], bool):
            raise LedgerError("INDEPENDENT_VERIFIER_BOOLEAN_REQUIRED")
        if record["topology"] == "SOLO_HATS" and record["independent_verifier"]:
            raise LedgerError("SOLO_INDEPENDENCE_FALSE_REQUIRED")
        if record["title"] != _bounded_text(record["title"], "title", 4096):
            raise LedgerError("TEXT_NOT_CANONICAL", "title")
        if record["body"] != _bounded_text(record["body"], "body", 10_485_760):
            raise LedgerError("TEXT_NOT_CANONICAL", "body")
        if (
            isinstance(record["body_bytes"], bool)
            or not isinstance(record["body_bytes"], int)
            or record["body_bytes"] < 0
            or record["body_bytes"] != len(record["body"].encode("utf-8"))
        ):
            raise LedgerError("BODY_BYTES_MISMATCH")
        observed_heads = _validate_observed_heads(record["observed_heads"])
        if observed_heads != record["observed_heads"]:
            raise LedgerError("OBSERVED_HEADS_NONCANONICAL")
        if (
            not isinstance(record["supersedes"], list)
            or len(set(record["supersedes"])) != len(record["supersedes"])
        ):
            raise LedgerError("SUPERSEDES_INVALID")
        for digest in record["supersedes"]:
            _hash(digest, "supersedes")
        for field in ("request_hash", "entry_hash"):
            _hash(record[field], field)
        _hash(record["prev_entry_hash"], "prev_entry_hash", nullable=True)
        _hash(
            record["prev_volume_seal_hash"],
            "prev_volume_seal_hash",
            nullable=True,
        )
        if record["integrity_scope"] != INTEGRITY_SCOPE:
            raise LedgerError("INTEGRITY_SCOPE_OVERCLAIM")
        if record["request_hash"] != self._request_hash_from_record(record):
            raise LedgerError("REQUEST_HASH_MISMATCH")
        core = dict(record)
        observed = core.pop("entry_hash")
        if observed != hash_core(ENTRY_DOMAIN, core):
            raise LedgerError("ENTRY_HASH_MISMATCH")

    def _request_hash_from_record(self, record: Mapping[str, Any]) -> str:
        intent = {
            key: record[key]
            for key in (
                "run_id",
                "stream_id",
                "event_id",
                "writer_id",
                "writer_instance_id",
                "lease_id",
                "fence",
                "topology",
                "hat",
                "independent_verifier",
                "kind",
                "title",
                "body",
                "body_bytes",
                "canonicalization_version",
                "observed_heads",
                "supersedes",
            )
        }
        return hash_core(REQUEST_DOMAIN, intent)

    def _validate_seal(
        self,
        number: int,
        path: Path,
        data: bytes,
        records: Sequence[dict[str, Any]],
        previous_seal_hash: str | None,
    ) -> dict[str, Any]:
        seal = _decode_canonical_record(_read_bytes(path), str(path))
        required = {
            "schema",
            "run_id",
            "stream_id",
            "volume_id",
            "volume_no",
            "first_seq",
            "last_seq",
            "entry_count",
            "byte_length",
            "file_sha256",
            "final_entry_hash",
            "previous_volume_seal_hash",
            "rotation_policy",
            "rotation_reasons",
            "phase_gate_id",
            "sealed_at",
            "integrity_scope",
            "seal_hash",
        }
        if set(seal) != required or seal.get("schema") != VOLUME_SEAL_SCHEMA:
            raise LedgerError("VOLUME_SEAL_MALFORMED", str(path))
        if not records:
            raise LedgerError("EMPTY_VOLUME_SEAL_FORBIDDEN", str(path))
        policy = _validate_rotation_policy_record(seal["rotation_policy"])
        phase_gate_id = seal["phase_gate_id"]
        if phase_gate_id is not None:
            _safe_id(phase_gate_id, "phase_gate_id")
        reasons = seal["rotation_reasons"]
        if (
            not isinstance(reasons, list)
            or len(reasons) != len(set(reasons))
            or any(reason not in ROTATION_REASON_ORDER for reason in reasons)
        ):
            raise LedgerError("ROTATION_REASONS_INVALID", str(path))
        manual_request = "MANUAL_REQUEST" in reasons
        expected_reasons = _rotation_reasons(
            len(records),
            len(data),
            policy,
            phase_gate_id=phase_gate_id,
            manual_request=manual_request,
        )
        if reasons != expected_reasons:
            raise LedgerError("ROTATION_REASON_BINDING_MISMATCH", str(path))
        expected = {
            "run_id": self.run_id,
            "stream_id": self.stream_id,
            "volume_id": self._volume_id(number),
            "volume_no": number,
            "first_seq": records[0]["stream_seq"],
            "last_seq": records[-1]["stream_seq"],
            "entry_count": len(records),
            "byte_length": len(data),
            "file_sha256": sha256_bytes(data),
            "final_entry_hash": records[-1]["entry_hash"],
            "previous_volume_seal_hash": previous_seal_hash,
            "rotation_policy": policy.as_record(),
            "rotation_reasons": expected_reasons,
            "phase_gate_id": phase_gate_id,
            "integrity_scope": INTEGRITY_SCOPE,
        }
        for key, value in expected.items():
            if seal.get(key) != value:
                raise LedgerError("VOLUME_SEAL_BINDING_MISMATCH", key)
        _parse_time(seal["sealed_at"], "sealed_at")
        core = dict(seal)
        observed = core.pop("seal_hash")
        if observed != hash_core(SEAL_DOMAIN, core):
            raise LedgerError("VOLUME_SEAL_HASH_MISMATCH", str(path))
        return seal

    def _validate_locked(self, *, allow_torn_tail: bool = False) -> dict[str, Any]:
        volumes = self._discover_volumes()
        leases_by_fence = {
            record["fence"]: record for record in self._load_leases_locked()
        }
        all_records: list[dict[str, Any]] = []
        locations: list[dict[str, Any]] = []
        records_by_volume: dict[int, list[dict[str, Any]]] = {}
        data_by_volume: dict[int, bytes] = {}
        seal_hashes: dict[int, str] = {}
        expected_seq = 1
        previous_entry_hash: str | None = None
        previous_seal_hash: str | None = None
        last_fence = 0
        fence_identity: dict[int, tuple[str, str, str]] = {}
        seen_events: set[str] = set()
        torn: dict[str, Any] | None = None

        for index, (number, path) in enumerate(volumes):
            data = _read_bytes(path)
            full_data = data
            is_last = index == len(volumes) - 1
            seal_path = self._seal_path(number)
            if data and not data.endswith(b"\n"):
                valid_bytes = data.rfind(b"\n") + 1
                fragment = data[valid_bytes:]
                if (
                    not allow_torn_tail
                    or not is_last
                    or seal_path.exists()
                    or not fragment
                ):
                    raise LedgerError("TORN_TAIL", str(path))
                data = data[:valid_bytes]
                torn = {
                    "volume_no": number,
                    "volume_id": self._volume_id(number),
                    "path": str(path),
                    "expected_file_sha256": sha256_bytes(full_data),
                    "expected_file_bytes": len(full_data),
                    "valid_bytes": valid_bytes,
                    "repaired_sha256": sha256_bytes(data),
                    "torn_bytes": len(fragment),
                    "torn_sha256": sha256_bytes(fragment),
                }
            volume_records: list[dict[str, Any]] = []
            offset = 0
            for raw_line in data.splitlines(keepends=True):
                if not raw_line.endswith(b"\n"):
                    raise LedgerError("TORN_TAIL", str(path))
                record = _decode_canonical_record(raw_line, str(path))
                self._validate_entry_shape(record)
                if (
                    record["run_id"] != self.run_id
                    or record["stream_id"] != self.stream_id
                    or record["volume_no"] != number
                    or record["volume_id"] != self._volume_id(number)
                    or record["topology"] != self.topology
                    or record["independent_verifier"] != self.independent_verifier
                ):
                    raise LedgerError("ENTRY_SCOPE_MISMATCH", str(path))
                if record["stream_seq"] != expected_seq:
                    raise LedgerError("STREAM_SEQUENCE_INVALID", str(path))
                if record["prev_entry_hash"] != previous_entry_hash:
                    raise LedgerError("ENTRY_CHAIN_BROKEN", str(path))
                expected_volume_seal = (
                    previous_seal_hash if not volume_records and number > 1 else None
                )
                if record["prev_volume_seal_hash"] != expected_volume_seal:
                    raise LedgerError("VOLUME_LINK_BROKEN", str(path))
                if record["event_id"] in seen_events:
                    raise LedgerError("EVENT_ID_DUPLICATE", record["event_id"])
                if record["fence"] < last_fence:
                    raise LedgerError("ENTRY_FENCE_ROLLBACK", str(path))
                identity = (
                    record["writer_id"],
                    record["writer_instance_id"],
                    record["lease_id"],
                )
                lease_record = leases_by_fence.get(record["fence"])
                if lease_record is None:
                    raise LedgerError("ENTRY_LEASE_NOT_FOUND", str(path))
                if identity != (
                    lease_record["writer_id"],
                    lease_record["writer_instance_id"],
                    lease_record["lease_id"],
                ):
                    raise LedgerError("ENTRY_LEASE_BINDING_MISMATCH", str(path))
                if record["fence"] in fence_identity and fence_identity[record["fence"]] != identity:
                    raise LedgerError("ENTRY_FENCE_IDENTITY_DRIFT", str(path))
                fence_identity[record["fence"]] = identity
                last_fence = record["fence"]
                seen_events.add(record["event_id"])
                previous_entry_hash = record["entry_hash"]
                expected_seq += 1
                offset += len(raw_line)
                volume_records.append(record)
                all_records.append(record)
                locations.append(
                    {
                        "volume_no": number,
                        "volume_id": self._volume_id(number),
                        "byte_offset": offset,
                    }
                )
            records_by_volume[number] = volume_records
            data_by_volume[number] = full_data
            if seal_path.exists():
                if torn:
                    raise LedgerError("SEALED_VOLUME_TORN", str(path))
                seal = self._validate_seal(
                    number,
                    seal_path,
                    full_data,
                    volume_records,
                    previous_seal_hash,
                )
                previous_seal_hash = seal["seal_hash"]
                seal_hashes[number] = seal["seal_hash"]
            elif not is_last:
                raise LedgerError("UNSEALED_PREDECESSOR_VOLUME", str(path))

        last_number = volumes[-1][0] if volumes else 0
        last_sealed = bool(last_number and last_number in seal_hashes)
        return {
            "records": all_records,
            "locations": locations,
            "records_by_volume": records_by_volume,
            "data_by_volume": data_by_volume,
            "seal_hashes": seal_hashes,
            "next_seq": expected_seq,
            "head_hash": previous_entry_hash,
            "last_volume_no": last_number,
            "last_volume_sealed": last_sealed,
            "torn": torn,
        }

    def validate(self) -> dict[str, Any]:
        with _exclusive_lock(self._lock_path):
            return self._validate_locked()

    def reconcile(self, event_id: str, request_hash: str | None = None) -> dict[str, Any] | None:
        _event_id(event_id)
        with _exclusive_lock(self._lock_path):
            state = self._validate_locked()
            for record in state["records"]:
                if record["event_id"] == event_id:
                    if request_hash is not None and record["request_hash"] != request_hash:
                        raise LedgerError("EVENT_ID_CONFLICT", event_id)
                    return record
            return None

    def append(
        self,
        lease: Lease,
        *,
        title: str,
        body: str,
        event_id: str | None = None,
        kind: str = "MESSAGE",
        hat: str = "BUILDER",
        observed_heads: Sequence[Mapping[str, Any]] = (),
        supersedes: Sequence[str] = (),
    ) -> dict[str, Any]:
        self._validate_lease_input(lease)
        event = _event_id(event_id or str(uuid.uuid4()))
        title_value = _bounded_text(title, "title", 4096)
        body_value = _bounded_text(body, "body", 10_485_760)
        body_bytes = len(body_value.encode("utf-8"))
        observed_heads_value = _validate_observed_heads(observed_heads)
        if kind not in {"MESSAGE", "CORRECTION", "CONTROL"}:
            raise LedgerError("ENTRY_KIND_INVALID")
        if hat not in {"BUILDER", "VERIFIER", "OTHER"}:
            raise LedgerError("HAT_INVALID")
        supersedes_value = list(supersedes)
        if len(set(supersedes_value)) != len(supersedes_value):
            raise LedgerError("SUPERSEDES_INVALID")
        for digest in supersedes_value:
            _hash(digest, "supersedes")

        intent = {
            "run_id": self.run_id,
            "stream_id": self.stream_id,
            "event_id": event,
            "writer_id": lease.writer_id,
            "writer_instance_id": lease.writer_instance_id,
            "lease_id": lease.lease_id,
            "fence": lease.fence,
            "topology": self.topology,
            "hat": hat,
            "independent_verifier": self.independent_verifier,
            "kind": kind,
            "title": title_value,
            "body": body_value,
            "body_bytes": body_bytes,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "observed_heads": observed_heads_value,
            "supersedes": supersedes_value,
        }
        request_hash = hash_core(REQUEST_DOMAIN, intent)

        with _exclusive_lock(self._lock_path):
            state = self._validate_locked()
            for record in state["records"]:
                if record["event_id"] == event:
                    if record["request_hash"] != request_hash:
                        raise LedgerError("EVENT_ID_CONFLICT", event)
                    rotation = self._rotation_for_reconciled_entry_locked(
                        lease, state, record
                    )
                    return {
                        "status": "RECONCILED",
                        "entry": record,
                        "rotation": rotation,
                    }

            self._require_active_lease_locked(lease)
            volume_no = state["last_volume_no"]
            if volume_no == 0:
                volume_no = 1
                self._create_empty_volume_locked(volume_no)
            elif state["last_volume_sealed"]:
                volume_no += 1
                self._create_empty_volume_locked(volume_no)
            path = self._volume_path(volume_no)
            prior_records = state["records_by_volume"].get(volume_no, [])
            prev_volume_seal = (
                state["seal_hashes"].get(volume_no - 1) if not prior_records else None
            )
            core = {
                "schema": ENTRY_SCHEMA,
                "run_id": self.run_id,
                "stream_id": self.stream_id,
                "volume_id": self._volume_id(volume_no),
                "volume_no": volume_no,
                "stream_seq": state["next_seq"],
                "event_id": event,
                "writer_id": lease.writer_id,
                "writer_instance_id": lease.writer_instance_id,
                "lease_id": lease.lease_id,
                "fence": lease.fence,
                "topology": self.topology,
                "hat": hat,
                "independent_verifier": self.independent_verifier,
                "created_at": _now(),
                "kind": kind,
                "title": title_value,
                "body": body_value,
                "body_bytes": body_bytes,
                "canonicalization_version": CANONICALIZATION_VERSION,
                "observed_heads": observed_heads_value,
                "supersedes": supersedes_value,
                "request_hash": request_hash,
                "prev_entry_hash": state["head_hash"],
                "prev_volume_seal_hash": prev_volume_seal,
                "integrity_scope": INTEGRITY_SCOPE,
            }
            record = {**core, "entry_hash": hash_core(ENTRY_DOMAIN, core)}
            encoded = canonical_line(record)
            before = path.stat()
            descriptor = os.open(
                path,
                os.O_WRONLY
                | os.O_APPEND
                | getattr(os, "O_BINARY", 0),
            )
            try:
                opened = os.fstat(descriptor)
                if not os.path.samestat(before, opened):
                    raise LedgerError("APPEND_FILE_IDENTITY_DRIFT", str(path))
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    os.fsync(descriptor)
                    raise LedgerError("AMBIGUOUS_SHORT_APPEND", str(path))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            observed = _read_bytes(path)
            start = len(observed) - len(encoded)
            if start < 0 or observed[start:] != encoded:
                raise LedgerError("APPEND_READBACK_MISMATCH", str(path))
            verified = self._validate_locked()
            if (
                not verified["records"]
                or verified["records"][-1]["entry_hash"] != record["entry_hash"]
                or verified["records"][-1]["event_id"] != event
            ):
                raise LedgerError("APPEND_TAIL_MISMATCH", str(path))
            rotation = self._apply_rotation_policy_locked(lease, verified)
            return {
                "status": "APPENDED",
                "entry": record,
                "rotation": rotation,
            }

    def _create_empty_volume_locked(self, number: int) -> None:
        path = self._volume_path(number)
        try:
            with path.open("xb") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(path.parent)
        except FileExistsError:
            if _read_bytes(path) != b"":
                raise LedgerError("VOLUME_CREATE_COLLISION", str(path))

    def _rotation_not_triggered(self) -> dict[str, Any]:
        return {
            "status": "ROTATION_NOT_TRIGGERED",
            "rotation_policy": self.rotation_policy.as_record(),
            "rotation_reasons": [],
        }

    def _rotation_for_reconciled_entry_locked(
        self,
        lease: Lease,
        state: Mapping[str, Any],
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        seal_path = self._seal_path(record["volume_no"])
        if seal_path.exists():
            seal = _decode_canonical_record(_read_bytes(seal_path), str(seal_path))
            return {
                "status": "ROTATION_RECONCILED",
                "seal": seal,
                "next_volume": str(self._volume_path(record["volume_no"] + 1)),
            }
        if state["records"] and state["records"][-1]["entry_hash"] == record["entry_hash"]:
            return self._apply_rotation_policy_locked(lease, state)
        return self._rotation_not_triggered()

    def _apply_rotation_policy_locked(
        self,
        lease: Lease,
        state: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        observed = state or self._validate_locked()
        number = observed["last_volume_no"]
        if number == 0 or observed["last_volume_sealed"]:
            return self._rotation_not_triggered()
        records = observed["records_by_volume"].get(number, [])
        if not records:
            return self._rotation_not_triggered()
        data = observed["data_by_volume"][number]
        reasons = _rotation_reasons(
            len(records), len(data), self.rotation_policy
        )
        if not reasons:
            return self._rotation_not_triggered()
        return self._seal_and_rotate_locked(
            lease,
            policy=self.rotation_policy,
            reasons=reasons,
            phase_gate_id=None,
        )

    def _seal_and_rotate_locked(
        self,
        lease: Lease,
        *,
        policy: RotationPolicy,
        reasons: Sequence[str],
        phase_gate_id: str | None,
    ) -> dict[str, Any]:
        reasons = list(reasons)
        state = self._validate_locked()
        self._require_active_lease_locked(lease)
        if not state["records"] or state["last_volume_no"] == 0:
            raise LedgerError("EMPTY_VOLUME_SEAL_FORBIDDEN")
        number = state["last_volume_no"]
        records = state["records_by_volume"].get(number, [])
        if not records:
            previous_number = number - 1
            previous_path = self._seal_path(previous_number)
            if previous_number > 0 and previous_path.exists():
                seal = _decode_canonical_record(
                    _read_bytes(previous_path), str(previous_path)
                )
                requested_marker = (
                    "PHASE_GATE"
                    if phase_gate_id is not None
                    else "MANUAL_REQUEST"
                    if "MANUAL_REQUEST" in reasons
                    else None
                )
                if (
                    seal.get("rotation_policy") == policy.as_record()
                    and seal.get("phase_gate_id") == phase_gate_id
                    and (
                        seal.get("rotation_reasons") == reasons
                        if requested_marker is None
                        else requested_marker in seal.get("rotation_reasons", [])
                    )
                ):
                    return {
                        "status": "ROTATION_RECONCILED",
                        "seal": seal,
                        "next_volume": str(self._volume_path(number)),
                    }
            raise LedgerError("EMPTY_VOLUME_SEAL_FORBIDDEN")
        data = state["data_by_volume"][number]
        expected_reasons = _rotation_reasons(
            len(records),
            len(data),
            policy,
            phase_gate_id=phase_gate_id,
            manual_request="MANUAL_REQUEST" in reasons,
        )
        if reasons != expected_reasons:
            raise LedgerError("ROTATION_REASON_BINDING_MISMATCH")
        seal_path = self._seal_path(number)
        if seal_path.exists():
            seal = _decode_canonical_record(_read_bytes(seal_path), str(seal_path))
            if (
                seal.get("rotation_policy") != policy.as_record()
                or seal.get("rotation_reasons") != expected_reasons
                or seal.get("phase_gate_id") != phase_gate_id
            ):
                raise LedgerError("ROTATION_RECONCILE_MISMATCH")
            next_number = number + 1
            self._create_empty_volume_locked(next_number)
            return {
                "status": "ROTATION_RECONCILED",
                "seal": seal,
                "next_volume": str(self._volume_path(next_number)),
            }
        previous_seal_hash = state["seal_hashes"].get(number - 1)
        core = {
            "schema": VOLUME_SEAL_SCHEMA,
            "run_id": self.run_id,
            "stream_id": self.stream_id,
            "volume_id": self._volume_id(number),
            "volume_no": number,
            "first_seq": records[0]["stream_seq"],
            "last_seq": records[-1]["stream_seq"],
            "entry_count": len(records),
            "byte_length": len(data),
            "file_sha256": sha256_bytes(data),
            "final_entry_hash": records[-1]["entry_hash"],
            "previous_volume_seal_hash": previous_seal_hash,
            "rotation_policy": policy.as_record(),
            "rotation_reasons": reasons,
            "phase_gate_id": phase_gate_id,
            "sealed_at": _now(),
            "integrity_scope": INTEGRITY_SCOPE,
        }
        seal = {**core, "seal_hash": hash_core(SEAL_DOMAIN, core)}
        _create_once(seal_path, canonical_line(seal))
        checked = self._validate_locked()
        if checked["seal_hashes"].get(number) != seal["seal_hash"]:
            raise LedgerError("VOLUME_SEAL_READBACK_MISMATCH")
        next_number = number + 1
        self._create_empty_volume_locked(next_number)
        final = self._validate_locked()
        if final["last_volume_no"] != next_number or final["last_volume_sealed"]:
            raise LedgerError("ROTATION_READBACK_MISMATCH")
        return {
            "status": "ROTATED",
            "seal": seal,
            "next_volume": str(self._volume_path(next_number)),
        }

    def seal_and_rotate(self, lease: Lease) -> dict[str, Any]:
        """Explicit manual rotation; thresholds remain recorded and checkable."""
        with _exclusive_lock(self._lock_path):
            state = self._validate_locked()
            number = state["last_volume_no"]
            records = state["records_by_volume"].get(number, [])
            if not records:
                reasons = ["MANUAL_REQUEST"]
            else:
                reasons = _rotation_reasons(
                    len(records),
                    len(state["data_by_volume"][number]),
                    self.rotation_policy,
                    manual_request=True,
                )
            return self._seal_and_rotate_locked(
                lease,
                policy=self.rotation_policy,
                reasons=reasons,
                phase_gate_id=None,
            )

    def rotate_for_phase_gate(
        self, lease: Lease, phase_gate_id: str
    ) -> dict[str, Any]:
        """Seal the current per-writer volume at one explicit phase boundary."""
        gate = _safe_id(phase_gate_id, "phase_gate_id")
        with _exclusive_lock(self._lock_path):
            state = self._validate_locked()
            number = state["last_volume_no"]
            records = state["records_by_volume"].get(number, [])
            if not records:
                reasons = ["PHASE_GATE"]
            else:
                reasons = _rotation_reasons(
                    len(records),
                    len(state["data_by_volume"][number]),
                    self.rotation_policy,
                    phase_gate_id=gate,
                )
            return self._seal_and_rotate_locked(
                lease,
                policy=self.rotation_policy,
                reasons=reasons,
                phase_gate_id=gate,
            )

    def inspect_torn_tail(self) -> dict[str, Any]:
        with _exclusive_lock(self._lock_path):
            state = self._validate_locked(allow_torn_tail=True)
            if state["torn"] is None:
                raise LedgerError("TORN_TAIL_NOT_FOUND")
            core = {
                "schema": TORN_PLAN_SCHEMA,
                "run_id": self.run_id,
                "stream_id": self.stream_id,
                **state["torn"],
                "required_action": "TRUNCATE_UNCOMMITTED_TAIL",
                "integrity_scope": INTEGRITY_SCOPE,
            }
            return {**core, "plan_hash": hash_core(PLAN_DOMAIN, core)}

    def repair_torn_tail(self, authority: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "schema",
            "action",
            "run_id",
            "stream_id",
            "volume_id",
            "expected_file_sha256",
            "expected_file_bytes",
            "valid_bytes",
            "repaired_sha256",
            "torn_bytes",
            "torn_sha256",
            "plan_hash",
            "authorized_by",
            "authority_id",
            "authority_source",
            "authorized_at",
            "expires_at",
        }
        if set(authority) != required:
            raise LedgerError("REPAIR_AUTHORITY_MALFORMED")
        if (
            authority["schema"] != REPAIR_AUTHORITY_SCHEMA
            or authority["action"] != "TRUNCATE_UNCOMMITTED_TAIL"
            or authority["run_id"] != self.run_id
            or authority["stream_id"] != self.stream_id
        ):
            raise LedgerError("REPAIR_AUTHORITY_BINDING_MISMATCH")
        _safe_id(authority["authorized_by"], "authorized_by")
        _safe_id(authority["authority_id"], "authority_id")
        if authority["authority_source"] not in {"HUMAN_EXPLICIT", "POLICY_BROKER"}:
            raise LedgerError("REPAIR_AUTHORITY_SOURCE_INVALID")
        _parse_time(authority["authorized_at"], "repair.authorized_at")
        if _parse_time(authority["expires_at"], "repair.expires_at") <= datetime.now(
            timezone.utc
        ):
            raise LedgerError("REPAIR_AUTHORITY_EXPIRED")

        with _exclusive_lock(self._lock_path):
            state = self._validate_locked(allow_torn_tail=True)
            if state["torn"] is None:
                raise LedgerError("TORN_TAIL_NOT_FOUND")
            plan_core = {
                "schema": TORN_PLAN_SCHEMA,
                "run_id": self.run_id,
                "stream_id": self.stream_id,
                **state["torn"],
                "required_action": "TRUNCATE_UNCOMMITTED_TAIL",
                "integrity_scope": INTEGRITY_SCOPE,
            }
            plan = {**plan_core, "plan_hash": hash_core(PLAN_DOMAIN, plan_core)}
            for key in (
                "volume_id",
                "expected_file_sha256",
                "expected_file_bytes",
                "valid_bytes",
                "repaired_sha256",
                "torn_bytes",
                "torn_sha256",
                "plan_hash",
            ):
                if authority.get(key) != plan[key]:
                    raise LedgerError("REPAIR_AUTHORITY_BINDING_MISMATCH", key)
            authority_hash = hash_core(AUTHORITY_DOMAIN, dict(authority))
            volume_no = state["torn"]["volume_no"]
            intent_core = {
                "schema": REPAIR_RECEIPT_SCHEMA,
                "status": "REPAIR_INTENT_RECORDED",
                "run_id": self.run_id,
                "stream_id": self.stream_id,
                "volume_id": plan["volume_id"],
                "volume_no": volume_no,
                "plan_hash": plan["plan_hash"],
                "authority_id": authority["authority_id"],
                "authority_hash": authority_hash,
                "expected_file_sha256": plan["expected_file_sha256"],
                "valid_bytes": plan["valid_bytes"],
                "repaired_sha256": plan["repaired_sha256"],
                "torn_bytes": plan["torn_bytes"],
                "torn_sha256": plan["torn_sha256"],
                "created_at": authority["authorized_at"],
                "integrity_scope": INTEGRITY_SCOPE,
            }
            intent = {
                **intent_core,
                "receipt_hash": hash_core(AUTHORITY_DOMAIN, intent_core),
            }
            _create_once(
                self._repair_path(volume_no, authority["authority_id"], "intent"),
                canonical_line(intent),
            )
            path = self._volume_path(volume_no)
            before = _read_bytes(path)
            if (
                len(before) != plan["expected_file_bytes"]
                or sha256_bytes(before) != plan["expected_file_sha256"]
            ):
                raise LedgerError("REPAIR_TARGET_DRIFT")
            with path.open("r+b") as handle:
                opened = os.fstat(handle.fileno())
                if opened.st_size != len(before):
                    raise LedgerError("REPAIR_TARGET_DRIFT")
                handle.truncate(plan["valid_bytes"])
                handle.flush()
                os.fsync(handle.fileno())
            after = _read_bytes(path)
            if (
                len(after) != plan["valid_bytes"]
                or sha256_bytes(after) != plan["repaired_sha256"]
            ):
                raise LedgerError("REPAIR_READBACK_MISMATCH")
            complete_core = {
                **intent_core,
                "status": "REPAIR_COMPLETE",
                "completed_at": _now(),
            }
            complete = {
                **complete_core,
                "receipt_hash": hash_core(AUTHORITY_DOMAIN, complete_core),
            }
            _create_once(
                self._repair_path(volume_no, authority["authority_id"], "complete"),
                canonical_line(complete),
            )
            verified = self._validate_locked()
            return {
                "status": "RECOVERED",
                "receipt": complete,
                "head_hash": verified["head_hash"],
                "next_seq": verified["next_seq"],
            }


def _validate_checkpoint_record(record: dict[str, Any]) -> None:
    required = {
        "schema",
        "run_id",
        "consumer_id",
        "created_at",
        "heads",
        "integrity_scope",
        "external_anchor_status",
        "checkpoint_hash",
    }
    if set(record) != required or record.get("schema") != CHECKPOINT_SCHEMA:
        raise LedgerError("CHECKPOINT_MALFORMED")
    _safe_id(record["run_id"], "run_id")
    _safe_id(record["consumer_id"], "consumer_id")
    _parse_time(record["created_at"], "checkpoint.created_at")
    if record["integrity_scope"] != INTEGRITY_SCOPE:
        raise LedgerError("INTEGRITY_SCOPE_OVERCLAIM")
    if record["external_anchor_status"] != "NOT_VERIFIED":
        raise LedgerError("EXTERNAL_ANCHOR_OVERCLAIM")
    if not isinstance(record["heads"], list) or not record["heads"]:
        raise LedgerError("CHECKPOINT_HEADS_INVALID")
    streams: list[str] = []
    for head in record["heads"]:
        if set(head) != {
            "stream_id",
            "volume_id",
            "volume_no",
            "stream_seq",
            "entry_hash",
            "byte_offset",
        }:
            raise LedgerError("CHECKPOINT_HEAD_MALFORMED")
        streams.append(_safe_id(head["stream_id"], "stream_id"))
        if any(
            isinstance(head[field], bool)
            or not isinstance(head[field], int)
            or head[field] < 0
            for field in ("volume_no", "stream_seq", "byte_offset")
        ):
            raise LedgerError("CHECKPOINT_HEAD_NUMBER_INVALID")
        if head["stream_seq"] == 0:
            if head["entry_hash"] is not None or head["volume_id"] is not None:
                raise LedgerError("CHECKPOINT_EMPTY_HEAD_INVALID")
        else:
            _hash(head["entry_hash"], "entry_hash")
            if not isinstance(head["volume_id"], str):
                raise LedgerError("CHECKPOINT_VOLUME_ID_INVALID")
    if streams != sorted(streams) or len(streams) != len(set(streams)):
        raise LedgerError("CHECKPOINT_HEAD_ORDER_INVALID")
    core = dict(record)
    observed = core.pop("checkpoint_hash")
    if observed != hash_core(CHECKPOINT_DOMAIN, core):
        raise LedgerError("CHECKPOINT_HASH_MISMATCH")


def read_vector_checkpoint(path: str | Path) -> dict[str, Any]:
    record = _decode_canonical_record(_read_bytes(Path(path)), str(path))
    _validate_checkpoint_record(record)
    return record


def write_vector_checkpoint(
    path: str | Path,
    consumer_id: str,
    ledgers: Iterable[RelayLedger],
) -> dict[str, Any]:
    ledgers_value = sorted(list(ledgers), key=lambda ledger: ledger.stream_id)
    if not ledgers_value:
        raise LedgerError("CHECKPOINT_LEDGER_SET_EMPTY")
    run_ids = {ledger.run_id for ledger in ledgers_value}
    streams = [ledger.stream_id for ledger in ledgers_value]
    if len(run_ids) != 1 or len(streams) != len(set(streams)):
        raise LedgerError("CHECKPOINT_LEDGER_SET_INVALID")
    _safe_id(consumer_id, "consumer_id")
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(target.with_name(f".{target.name}.lock")):
        heads: list[dict[str, Any]] = []
        for ledger in ledgers_value:
            state = ledger.validate()
            if state["records"]:
                last = state["records"][-1]
                location = state["locations"][-1]
                head = {
                    "stream_id": ledger.stream_id,
                    "volume_id": location["volume_id"],
                    "volume_no": location["volume_no"],
                    "stream_seq": last["stream_seq"],
                    "entry_hash": last["entry_hash"],
                    "byte_offset": location["byte_offset"],
                }
            else:
                head = {
                    "stream_id": ledger.stream_id,
                    "volume_id": None,
                    "volume_no": 0,
                    "stream_seq": 0,
                    "entry_hash": None,
                    "byte_offset": 0,
                }
            heads.append(head)
        core = {
            "schema": CHECKPOINT_SCHEMA,
            "run_id": ledgers_value[0].run_id,
            "consumer_id": consumer_id,
            "created_at": _now(),
            "heads": heads,
            "integrity_scope": INTEGRITY_SCOPE,
            "external_anchor_status": "NOT_VERIFIED",
        }
        record = {
            **core,
            "checkpoint_hash": hash_core(CHECKPOINT_DOMAIN, core),
        }
        _atomic_replace(target, canonical_line(record))
        observed = read_vector_checkpoint(target)
        if observed != record:
            raise LedgerError("CHECKPOINT_READBACK_MISMATCH")
        return observed


def verify_vector_checkpoint(
    checkpoint: str | Path | Mapping[str, Any],
    ledgers: Iterable[RelayLedger],
) -> dict[str, list[dict[str, Any]]]:
    if isinstance(checkpoint, (str, Path)):
        record = read_vector_checkpoint(checkpoint)
    else:
        record = dict(checkpoint)
        _validate_checkpoint_record(record)
    ledger_by_stream = {ledger.stream_id: ledger for ledger in ledgers}
    expected_streams = {head["stream_id"] for head in record["heads"]}
    if set(ledger_by_stream) != expected_streams:
        raise LedgerError("CHECKPOINT_STREAM_SET_MISMATCH")
    higher: dict[str, list[dict[str, Any]]] = {}
    for head in record["heads"]:
        ledger = ledger_by_stream[head["stream_id"]]
        if ledger.run_id != record["run_id"]:
            raise LedgerError("CHECKPOINT_RUN_MISMATCH")
        state = ledger.validate()
        sequence = head["stream_seq"]
        if len(state["records"]) < sequence:
            raise LedgerError("CHECKPOINT_AHEAD_OF_LEDGER", ledger.stream_id)
        if sequence:
            location = state["locations"][sequence - 1]
            if (
                state["records"][sequence - 1]["entry_hash"] != head["entry_hash"]
                or location["volume_id"] != head["volume_id"]
                or location["volume_no"] != head["volume_no"]
                or location["byte_offset"] != head["byte_offset"]
            ):
                raise LedgerError("CHECKPOINT_DIVERGENCE", ledger.stream_id)
        higher[ledger.stream_id] = state["records"][sequence:]
    return higher


def _normalize_anchor_ledgers(
    ledgers: Iterable[RelayLedger],
) -> list[RelayLedger]:
    result = sorted(list(ledgers), key=lambda ledger: ledger.stream_id)
    if not result:
        raise LedgerError("ANCHOR_LEDGER_SET_EMPTY")
    if len({ledger.run_id for ledger in result}) != 1:
        raise LedgerError("ANCHOR_RUN_SET_INVALID")
    streams = [ledger.stream_id for ledger in result]
    if len(streams) != len(set(streams)):
        raise LedgerError("ANCHOR_STREAM_SET_INVALID")
    return result


def _anchor_subject_for_root(
    root: Path,
    anchor_set_id: str,
    ledgers: Sequence[RelayLedger],
) -> dict[str, Any]:
    return {
        "schema": EXTERNAL_ANCHOR_SUBJECT_SCHEMA,
        "anchor_set_id": _safe_id(anchor_set_id, "anchor_set_id"),
        "run_id": ledgers[0].run_id,
        "anchor_root_fingerprint": _path_fingerprint(root),
        "ledger_roots": [
            {
                "stream_id": ledger.stream_id,
                "root_fingerprint": _path_fingerprint(ledger.root),
            }
            for ledger in ledgers
        ],
    }


def external_anchor_qualification_subject(
    anchor_root: str | Path,
    anchor_set_id: str,
    ledgers: Iterable[RelayLedger],
) -> dict[str, Any]:
    """Return the exact subject a caller must qualify; this grants no trust."""
    ledger_set = _normalize_anchor_ledgers(ledgers)
    root = _resolve_external_anchor_root(anchor_root, ledger_set, create=True)
    return _anchor_subject_for_root(root, anchor_set_id, ledger_set)


def _trust_domain_record(
    qualification: Mapping[str, Any] | None,
    subject: Mapping[str, Any],
) -> dict[str, Any]:
    if qualification is None:
        return {
            "status": "UNQUALIFIED",
            "trust_domain_id": None,
            "qualification_id": None,
            "basis": None,
            "evidence_sha256": None,
            "qualification_hash": None,
        }
    required = {
        "schema",
        "status",
        "anchor_set_id",
        "run_id",
        "anchor_root_fingerprint",
        "ledger_roots",
        "trust_domain_id",
        "qualification_id",
        "qualified_by",
        "basis",
        "evidence_sha256",
        "qualified_at",
        "expires_at",
    }
    if set(qualification) != required:
        raise LedgerError("ANCHOR_QUALIFICATION_MALFORMED")
    expected = {
        "schema": EXTERNAL_ANCHOR_QUALIFICATION_SCHEMA,
        "status": "CALLER_QUALIFIED_UNVERIFIED",
        "anchor_set_id": subject["anchor_set_id"],
        "run_id": subject["run_id"],
        "anchor_root_fingerprint": subject["anchor_root_fingerprint"],
        "ledger_roots": subject["ledger_roots"],
    }
    for key, value in expected.items():
        if qualification.get(key) != value:
            raise LedgerError("ANCHOR_QUALIFICATION_BINDING_MISMATCH", key)
    for field in ("trust_domain_id", "qualification_id", "qualified_by"):
        _safe_id(qualification[field], field)
    if qualification["basis"] not in {
        "SEPARATE_PRINCIPAL_APPEND_ONLY",
        "WORM",
        "TRANSPARENCY_LOG",
        "PROTECTED_REMOTE",
    }:
        raise LedgerError("ANCHOR_QUALIFICATION_BASIS_INVALID")
    _hash(qualification["evidence_sha256"], "qualification.evidence_sha256")
    _parse_time(qualification["qualified_at"], "qualification.qualified_at")
    if _parse_time(
        qualification["expires_at"], "qualification.expires_at"
    ) <= datetime.now(timezone.utc):
        raise LedgerError("ANCHOR_QUALIFICATION_EXPIRED")
    return {
        "status": "CALLER_QUALIFIED_UNVERIFIED",
        "trust_domain_id": qualification["trust_domain_id"],
        "qualification_id": qualification["qualification_id"],
        "basis": qualification["basis"],
        "evidence_sha256": qualification["evidence_sha256"],
        "qualification_hash": hash_core(
            EXTERNAL_ANCHOR_QUALIFICATION_DOMAIN, dict(qualification)
        ),
    }


def _build_external_anchor_head(ledger: RelayLedger) -> dict[str, Any]:
    with _exclusive_lock(ledger._lock_path):
        state = ledger._validate_locked()
        root_fingerprint = _path_fingerprint(ledger.root)
        if not state["records"]:
            return {
                "stream_id": ledger.stream_id,
                "ledger_root_fingerprint": root_fingerprint,
                "volume_id": None,
                "volume_no": 0,
                "stream_seq": 0,
                "entry_hash": None,
                "byte_offset": 0,
                "anchored_prefix_sha256": sha256_bytes(b""),
                "volume_seal_hash": None,
            }
        record = state["records"][-1]
        location = state["locations"][-1]
        volume_data = _read_bytes(ledger._volume_path(location["volume_no"]))
        if len(volume_data) < location["byte_offset"]:
            raise LedgerError("ANCHOR_HEAD_OFFSET_INVALID", ledger.stream_id)
        prefix = volume_data[: location["byte_offset"]]
        return {
            "stream_id": ledger.stream_id,
            "ledger_root_fingerprint": root_fingerprint,
            "volume_id": location["volume_id"],
            "volume_no": location["volume_no"],
            "stream_seq": record["stream_seq"],
            "entry_hash": record["entry_hash"],
            "byte_offset": location["byte_offset"],
            "anchored_prefix_sha256": sha256_bytes(prefix),
            "volume_seal_hash": state["seal_hashes"].get(location["volume_no"]),
        }


def _validate_anchor_head(head: Mapping[str, Any]) -> None:
    required = {
        "stream_id",
        "ledger_root_fingerprint",
        "volume_id",
        "volume_no",
        "stream_seq",
        "entry_hash",
        "byte_offset",
        "anchored_prefix_sha256",
        "volume_seal_hash",
    }
    if set(head) != required:
        raise LedgerError("EXTERNAL_ANCHOR_HEAD_MALFORMED")
    _safe_id(head["stream_id"], "anchor.head.stream_id")
    _hash(head["ledger_root_fingerprint"], "anchor.head.ledger_root_fingerprint")
    _hash(head["anchored_prefix_sha256"], "anchor.head.anchored_prefix_sha256")
    for field in ("volume_no", "stream_seq", "byte_offset"):
        value = head[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LedgerError("EXTERNAL_ANCHOR_HEAD_NUMBER_INVALID", field)
    if head["stream_seq"] == 0:
        if (
            head["volume_id"] is not None
            or head["entry_hash"] is not None
            or head["volume_no"] != 0
            or head["byte_offset"] != 0
            or head["volume_seal_hash"] is not None
            or head["anchored_prefix_sha256"] != sha256_bytes(b"")
        ):
            raise LedgerError("EXTERNAL_ANCHOR_EMPTY_HEAD_INVALID")
    else:
        if not isinstance(head["volume_id"], str):
            raise LedgerError("EXTERNAL_ANCHOR_VOLUME_ID_INVALID")
        _positive_int(head["volume_no"], "anchor.head.volume_no")
        _positive_int(head["stream_seq"], "anchor.head.stream_seq")
        _positive_int(head["byte_offset"], "anchor.head.byte_offset")
        _hash(head["entry_hash"], "anchor.head.entry_hash")
        _hash(
            head["volume_seal_hash"],
            "anchor.head.volume_seal_hash",
            nullable=True,
        )


def _validate_external_anchor_record(record: Mapping[str, Any]) -> None:
    required = {
        "schema",
        "anchor_set_id",
        "run_id",
        "anchor_seq",
        "created_at",
        "previous_anchor_hash",
        "anchor_root_fingerprint",
        "qualification_subject_hash",
        "heads",
        "heads_hash",
        "trust_domain",
        "anchor_scope",
        "anchor_hash",
    }
    if set(record) != required or record.get("schema") != EXTERNAL_ANCHOR_SCHEMA:
        raise LedgerError("EXTERNAL_ANCHOR_MALFORMED")
    _safe_id(record["anchor_set_id"], "anchor_set_id")
    _safe_id(record["run_id"], "run_id")
    _positive_int(record["anchor_seq"], "anchor_seq")
    _parse_time(record["created_at"], "anchor.created_at")
    _hash(record["previous_anchor_hash"], "previous_anchor_hash", nullable=True)
    _hash(record["anchor_root_fingerprint"], "anchor_root_fingerprint")
    _hash(record["qualification_subject_hash"], "qualification_subject_hash")
    _hash(record["heads_hash"], "heads_hash")
    _hash(record["anchor_hash"], "anchor_hash")
    if record["anchor_scope"] != EXTERNAL_ANCHOR_SCOPE:
        raise LedgerError("EXTERNAL_ANCHOR_SCOPE_INVALID")
    if not isinstance(record["heads"], list) or not record["heads"]:
        raise LedgerError("EXTERNAL_ANCHOR_HEADS_INVALID")
    streams: list[str] = []
    for head in record["heads"]:
        if not isinstance(head, dict):
            raise LedgerError("EXTERNAL_ANCHOR_HEAD_MALFORMED")
        _validate_anchor_head(head)
        streams.append(head["stream_id"])
    if streams != sorted(streams) or len(streams) != len(set(streams)):
        raise LedgerError("EXTERNAL_ANCHOR_HEAD_ORDER_INVALID")
    if record["heads_hash"] != hash_core(
        EXTERNAL_ANCHOR_HEADS_DOMAIN, {"heads": record["heads"]}
    ):
        raise LedgerError("EXTERNAL_ANCHOR_HEADS_HASH_MISMATCH")
    trust = record["trust_domain"]
    trust_fields = {
        "status",
        "trust_domain_id",
        "qualification_id",
        "basis",
        "evidence_sha256",
        "qualification_hash",
    }
    if not isinstance(trust, dict) or set(trust) != trust_fields:
        raise LedgerError("EXTERNAL_ANCHOR_TRUST_RECORD_MALFORMED")
    if trust["status"] == "UNQUALIFIED":
        if any(trust[field] is not None for field in trust_fields - {"status"}):
            raise LedgerError("EXTERNAL_ANCHOR_UNQUALIFIED_OVERCLAIM")
    elif trust["status"] == "CALLER_QUALIFIED_UNVERIFIED":
        for field in ("trust_domain_id", "qualification_id"):
            _safe_id(trust[field], f"anchor.trust.{field}")
        if trust["basis"] not in {
            "SEPARATE_PRINCIPAL_APPEND_ONLY",
            "WORM",
            "TRANSPARENCY_LOG",
            "PROTECTED_REMOTE",
        }:
            raise LedgerError("ANCHOR_QUALIFICATION_BASIS_INVALID")
        for field in ("evidence_sha256", "qualification_hash"):
            _hash(trust[field], f"anchor.trust.{field}")
    else:
        raise LedgerError("EXTERNAL_ANCHOR_TRUST_STATUS_INVALID")
    core = dict(record)
    observed = core.pop("anchor_hash")
    if observed != hash_core(EXTERNAL_ANCHOR_DOMAIN, core):
        raise LedgerError("EXTERNAL_ANCHOR_HASH_MISMATCH")


def _external_anchor_path(root: Path, anchor_set_id: str, sequence: int) -> Path:
    return root / f"{anchor_set_id}.anchor.{sequence:020d}.json"


def _load_external_anchors(
    root: Path,
    anchor_set_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    paths: list[tuple[int, Path]] = []
    for path in root.glob(f"{anchor_set_id}.anchor.*.json"):
        match = EXTERNAL_ANCHOR_FILE.fullmatch(path.name)
        if match and match.group("anchor") == anchor_set_id:
            paths.append((int(match.group("sequence")), path))
    paths.sort()
    if paths and [sequence for sequence, _ in paths] != list(
        range(1, paths[-1][0] + 1)
    ):
        raise LedgerError("EXTERNAL_ANCHOR_SEQUENCE_GAP")
    records: list[dict[str, Any]] = []
    previous_hash: str | None = None
    root_fingerprint = _path_fingerprint(root)
    previous_heads: dict[str, dict[str, Any]] | None = None
    for sequence, path in paths:
        record = _decode_canonical_record(_read_bytes(path), str(path))
        _validate_external_anchor_record(record)
        if (
            record["anchor_set_id"] != anchor_set_id
            or record["run_id"] != run_id
            or record["anchor_seq"] != sequence
            or record["anchor_root_fingerprint"] != root_fingerprint
        ):
            raise LedgerError("EXTERNAL_ANCHOR_SCOPE_MISMATCH", str(path))
        if record["previous_anchor_hash"] != previous_hash:
            raise LedgerError("EXTERNAL_ANCHOR_CHAIN_BROKEN", str(path))
        current_heads = {head["stream_id"]: head for head in record["heads"]}
        if previous_heads is not None:
            if set(current_heads) != set(previous_heads):
                raise LedgerError("EXTERNAL_ANCHOR_STREAM_SET_DRIFT", str(path))
            for stream_id, old in previous_heads.items():
                new = current_heads[stream_id]
                if new["ledger_root_fingerprint"] != old["ledger_root_fingerprint"]:
                    raise LedgerError("EXTERNAL_ANCHOR_ROOT_DRIFT", stream_id)
                if new["stream_seq"] < old["stream_seq"]:
                    raise LedgerError("EXTERNAL_ANCHOR_HEAD_ROLLBACK", stream_id)
                if (
                    new["stream_seq"] == old["stream_seq"]
                    and new["entry_hash"] != old["entry_hash"]
                ):
                    raise LedgerError("EXTERNAL_ANCHOR_HEAD_DIVERGENCE", stream_id)
        previous_hash = record["anchor_hash"]
        previous_heads = current_heads
        records.append(record)
    return records


def create_external_anchor(
    anchor_root: str | Path,
    anchor_set_id: str,
    anchor_seq: int,
    ledgers: Iterable[RelayLedger],
    *,
    qualification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one O_EXCL vector-head anchor in a distinct caller-owned root."""
    ledger_set = _normalize_anchor_ledgers(ledgers)
    _safe_id(anchor_set_id, "anchor_set_id")
    _positive_int(anchor_seq, "anchor_seq")
    root = _resolve_external_anchor_root(anchor_root, ledger_set, create=True)
    subject = _anchor_subject_for_root(root, anchor_set_id, ledger_set)
    trust_domain = _trust_domain_record(qualification, subject)
    lock_path = root / f".{anchor_set_id}.anchor.lock"
    with _exclusive_lock(lock_path):
        existing = _load_external_anchors(
            root, anchor_set_id, ledger_set[0].run_id
        )
        expected_sequence = len(existing) + 1
        if anchor_seq != expected_sequence:
            raise LedgerError(
                "EXTERNAL_ANCHOR_SEQUENCE_INVALID",
                f"expected={expected_sequence}:observed={anchor_seq}",
            )
        heads = [_build_external_anchor_head(ledger) for ledger in ledger_set]
        if existing:
            old_heads = {
                head["stream_id"]: head for head in existing[-1]["heads"]
            }
            if set(old_heads) != {head["stream_id"] for head in heads}:
                raise LedgerError("EXTERNAL_ANCHOR_STREAM_SET_DRIFT")
            for head in heads:
                old = old_heads[head["stream_id"]]
                if head["ledger_root_fingerprint"] != old["ledger_root_fingerprint"]:
                    raise LedgerError(
                        "EXTERNAL_ANCHOR_ROOT_DRIFT", head["stream_id"]
                    )
                if head["stream_seq"] < old["stream_seq"]:
                    raise LedgerError(
                        "EXTERNAL_ANCHOR_HEAD_ROLLBACK", head["stream_id"]
                    )
                if (
                    head["stream_seq"] == old["stream_seq"]
                    and head["entry_hash"] != old["entry_hash"]
                ):
                    raise LedgerError(
                        "EXTERNAL_ANCHOR_HEAD_DIVERGENCE", head["stream_id"]
                    )
        heads_hash = hash_core(EXTERNAL_ANCHOR_HEADS_DOMAIN, {"heads": heads})
        subject_hash = hash_core(
            EXTERNAL_ANCHOR_QUALIFICATION_DOMAIN, subject
        )
        core = {
            "schema": EXTERNAL_ANCHOR_SCHEMA,
            "anchor_set_id": anchor_set_id,
            "run_id": ledger_set[0].run_id,
            "anchor_seq": anchor_seq,
            "created_at": _now(),
            "previous_anchor_hash": existing[-1]["anchor_hash"] if existing else None,
            "anchor_root_fingerprint": subject["anchor_root_fingerprint"],
            "qualification_subject_hash": subject_hash,
            "heads": heads,
            "heads_hash": heads_hash,
            "trust_domain": trust_domain,
            "anchor_scope": EXTERNAL_ANCHOR_SCOPE,
        }
        anchor = {
            **core,
            "anchor_hash": hash_core(EXTERNAL_ANCHOR_DOMAIN, core),
        }
        path = _external_anchor_path(root, anchor_set_id, anchor_seq)
        create_status = _create_once(path, canonical_line(anchor))
        readback = _load_external_anchors(
            root, anchor_set_id, ledger_set[0].run_id
        )
        if not readback or readback[-1] != anchor:
            raise LedgerError("EXTERNAL_ANCHOR_READBACK_MISMATCH")
        return {
            "status": "ANCHOR_CREATED"
            if create_status == "CREATED"
            else "ANCHOR_RECONCILED",
            "trust_domain_status": trust_domain["status"],
            "path": str(path),
            "anchor": anchor,
        }


def verify_external_anchor(
    anchor_root: str | Path,
    anchor_set_id: str,
    ledgers: Iterable[RelayLedger],
    *,
    anchor_seq: int | None = None,
    require_qualified: bool = False,
) -> dict[str, Any]:
    """Compare a create-once external vector head with current local histories."""
    ledger_set = _normalize_anchor_ledgers(ledgers)
    root = _resolve_external_anchor_root(anchor_root, ledger_set, create=False)
    records = _load_external_anchors(root, anchor_set_id, ledger_set[0].run_id)
    if not records:
        raise LedgerError("EXTERNAL_ANCHOR_NOT_FOUND")
    if anchor_seq is None:
        anchor = records[-1]
    else:
        _positive_int(anchor_seq, "anchor_seq")
        if anchor_seq > len(records):
            raise LedgerError("EXTERNAL_ANCHOR_NOT_FOUND", str(anchor_seq))
        anchor = records[anchor_seq - 1]
    subject = _anchor_subject_for_root(root, anchor_set_id, ledger_set)
    if anchor["qualification_subject_hash"] != hash_core(
        EXTERNAL_ANCHOR_QUALIFICATION_DOMAIN, subject
    ):
        raise LedgerError("EXTERNAL_ANCHOR_SUBJECT_DIVERGENCE")
    ledger_by_stream = {ledger.stream_id: ledger for ledger in ledger_set}
    if set(ledger_by_stream) != {head["stream_id"] for head in anchor["heads"]}:
        raise LedgerError("EXTERNAL_ANCHOR_STREAM_SET_DRIFT")
    for head in anchor["heads"]:
        ledger = ledger_by_stream[head["stream_id"]]
        if head["ledger_root_fingerprint"] != _path_fingerprint(ledger.root):
            raise LedgerError("EXTERNAL_ANCHOR_ROOT_DRIFT", ledger.stream_id)
        with _exclusive_lock(ledger._lock_path):
            state = ledger._validate_locked()
            sequence = head["stream_seq"]
            if len(state["records"]) < sequence:
                raise LedgerError("EXTERNAL_ANCHOR_LOCAL_ROLLBACK", ledger.stream_id)
            if sequence == 0:
                continue
            record = state["records"][sequence - 1]
            location = state["locations"][sequence - 1]
            if (
                record["entry_hash"] != head["entry_hash"]
                or location["volume_id"] != head["volume_id"]
                or location["volume_no"] != head["volume_no"]
                or location["byte_offset"] != head["byte_offset"]
            ):
                raise LedgerError("EXTERNAL_ANCHOR_HEAD_DIVERGENCE", ledger.stream_id)
            data = _read_bytes(ledger._volume_path(location["volume_no"]))
            if len(data) < head["byte_offset"]:
                raise LedgerError("EXTERNAL_ANCHOR_LOCAL_ROLLBACK", ledger.stream_id)
            if sha256_bytes(data[: head["byte_offset"]]) != head[
                "anchored_prefix_sha256"
            ]:
                raise LedgerError(
                    "EXTERNAL_ANCHOR_VOLUME_PREFIX_DIVERGENCE", ledger.stream_id
                )
            if (
                head["volume_seal_hash"] is not None
                and state["seal_hashes"].get(location["volume_no"])
                != head["volume_seal_hash"]
            ):
                raise LedgerError(
                    "EXTERNAL_ANCHOR_VOLUME_SEAL_DIVERGENCE", ledger.stream_id
                )
    trust_status = anchor["trust_domain"]["status"]
    if require_qualified and trust_status != "CALLER_QUALIFIED_UNVERIFIED":
        raise LedgerError("ANCHOR_TRUST_DOMAIN_UNQUALIFIED")
    return {
        "status": "ANCHOR_VERIFIED_CALLER_QUALIFIED_UNVERIFIED"
        if trust_status == "CALLER_QUALIFIED_UNVERIFIED"
        else "ANCHOR_VERIFIED_UNQUALIFIED",
        "anchor_seq": anchor["anchor_seq"],
        "anchor_hash": anchor["anchor_hash"],
        "trust_domain_status": trust_status,
        "streams_verified": len(anchor["heads"]),
    }


def _ledgers_from_spec(path: str | Path, expected_run_id: str) -> list[RelayLedger]:
    try:
        document = strict_json(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise LedgerError("LEDGER_SPEC_READ_FAILED", str(path)) from error
    if not isinstance(document, dict) or set(document) != {"run_id", "streams"}:
        raise LedgerError("LEDGER_SPEC_MALFORMED")
    if document["run_id"] != expected_run_id or not isinstance(
        document["streams"], list
    ):
        raise LedgerError("LEDGER_SPEC_SCOPE_MISMATCH")
    ledgers: list[RelayLedger] = []
    for stream in document["streams"]:
        if not isinstance(stream, dict) or set(stream) != {
            "root",
            "stream_id",
            "topology",
            "independent_verifier",
        }:
            raise LedgerError("LEDGER_SPEC_STREAM_MALFORMED")
        ledgers.append(
            RelayLedger(
                stream["root"],
                expected_run_id,
                stream["stream_id"],
                topology=stream["topology"],
                independent_verifier=stream["independent_verifier"],
            )
        )
    return _normalize_anchor_ledgers(ledgers)


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("validate", "inspect-torn", "anchor-create", "anchor-verify"),
    )
    parser.add_argument("root")
    parser.add_argument("run_id")
    parser.add_argument("stream_id", nargs="?")
    parser.add_argument("--topology", choices=("TEAM", "SOLO_HATS"), default="TEAM")
    parser.add_argument("--independent-verifier", action="store_true")
    parser.add_argument("--ledger-spec")
    parser.add_argument("--anchor-set-id")
    parser.add_argument("--anchor-seq", type=int)
    parser.add_argument("--qualification")
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action in {"validate", "inspect-torn"}:
            if args.stream_id is None:
                raise LedgerError("STREAM_ID_REQUIRED")
            ledger = RelayLedger(
                args.root,
                args.run_id,
                args.stream_id,
                topology=args.topology,
                independent_verifier=args.independent_verifier,
            )
            result = (
                ledger.validate()
                if args.action == "validate"
                else ledger.inspect_torn_tail()
            )
            summary = {
                "status": "PASS",
                "action": args.action,
                "stream_id": ledger.stream_id,
                "entry_count": len(result.get("records", [])),
                "head_hash": result.get("head_hash"),
                "torn_plan": result if args.action == "inspect-torn" else None,
            }
        else:
            if args.ledger_spec is None or args.anchor_set_id is None:
                raise LedgerError("ANCHOR_CLI_ARGUMENTS_REQUIRED")
            ledgers = _ledgers_from_spec(args.ledger_spec, args.run_id)
            if args.action == "anchor-create":
                if args.anchor_seq is None:
                    raise LedgerError("ANCHOR_SEQUENCE_REQUIRED")
                qualification = None
                if args.qualification:
                    try:
                        qualification_value = strict_json(
                            Path(args.qualification).read_text(encoding="utf-8")
                        )
                    except OSError as error:
                        raise LedgerError(
                            "ANCHOR_QUALIFICATION_READ_FAILED", args.qualification
                        ) from error
                    if not isinstance(qualification_value, dict):
                        raise LedgerError("ANCHOR_QUALIFICATION_MALFORMED")
                    qualification = qualification_value
                summary = create_external_anchor(
                    args.root,
                    args.anchor_set_id,
                    args.anchor_seq,
                    ledgers,
                    qualification=qualification,
                )
            else:
                summary = verify_external_anchor(
                    args.root,
                    args.anchor_set_id,
                    ledgers,
                    anchor_seq=args.anchor_seq,
                    require_qualified=args.require_qualified,
                )
        print(canonical_json(summary))
        return 0
    except LedgerError as error:
        print(
            canonical_json(
                {
                    "status": "BLOCKED",
                    "error": error.code,
                    "detail": error.detail,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
