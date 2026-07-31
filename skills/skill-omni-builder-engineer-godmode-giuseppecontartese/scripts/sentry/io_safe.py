"""Deterministic, crash-aware file primitives used by the sentry scripts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any, Iterable

TREE_ALGORITHM = "SHA256(canonical_json(files:v1))"
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


class PathSafetyError(ValueError):
    """A native path is ambiguous, outside its root, or crosses a reparse point."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def strict_json(text: str) -> Any:
    """Reject BOM, floats, NaN/Infinity, and duplicate keys before state use."""
    if text.startswith("\ufeff"):
        raise ValueError("JSON_BOM_FORBIDDEN")

    def no_float(value: str) -> None:
        raise ValueError(f"JSON_FLOAT_FORBIDDEN:{value}")

    def no_constant(value: str) -> None:
        raise ValueError(f"JSON_CONSTANT_FORBIDDEN:{value}")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON_DUPLICATE_KEY:{key}")
            result[key] = value
        return result

    return json.loads(text, parse_float=no_float, parse_constant=no_constant, object_pairs_hook=unique_pairs)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_path(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _is_reparse_point(path: Path) -> bool:
    """Recognise symlinks, junctions and other Windows reparse points."""
    try:
        if path.is_symlink() or (
            hasattr(path, "is_junction") and path.is_junction()
        ):
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except FileNotFoundError:
        return False
    except OSError as error:
        raise PathSafetyError(f"PATH_METADATA_UNREADABLE:{path}") from error


def _validate_native_absolute(path_value: str | Path, label: str) -> Path:
    value = str(path_value)
    if not value or "\x00" in value:
        raise PathSafetyError(f"ABSOLUTE_PATH_REQUIRED:{label}")
    normalized = value.replace("/", "\\")
    if normalized.startswith(("\\\\?\\", "\\\\.\\")):
        raise PathSafetyError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise PathSafetyError(f"ABSOLUTE_PATH_REQUIRED:{label}")
    windows = PureWindowsPath(value)
    drive_colon = 1 if len(windows.drive) == 2 and windows.drive[1] == ":" else None
    if any(index != drive_colon for index, char in enumerate(value) if char == ":"):
        raise PathSafetyError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    for part in windows.parts[1:]:
        if part in {"\\", "/"}:
            continue
        if part.endswith((" ", ".")):
            raise PathSafetyError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            raise PathSafetyError(f"AMBIGUOUS_PATH_FORBIDDEN:{label}")
    return candidate


def assert_safe_ancestors(path: str | Path, *, include_target: bool = True) -> None:
    """Reject every existing reparse-bearing component of an absolute path."""
    candidate = _validate_native_absolute(path, "PATH")
    parts = candidate.parts
    if not parts:
        raise PathSafetyError("ABSOLUTE_PATH_REQUIRED:PATH")
    current = Path(parts[0])
    last = len(parts) if include_target else max(1, len(parts) - 1)
    for part in parts[1:last]:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_reparse_point(current):
                raise PathSafetyError(f"REPARSE_POINT_FORBIDDEN:{current}")


def _ancestor_identity_snapshot(
    path: str | Path, *, include_target: bool = True
) -> tuple[tuple[str, int, int, int], ...]:
    """Capture existing ancestor identities so a late junction swap is visible."""
    candidate = _validate_native_absolute(path, "PATH")
    parts = candidate.parts
    current = Path(parts[0])
    last = len(parts) if include_target else max(1, len(parts) - 1)
    identities: list[tuple[str, int, int, int]] = []
    for part in parts[1:last]:
        current = current / part
        if not (current.exists() or current.is_symlink()):
            continue
        if _is_reparse_point(current):
            raise PathSafetyError(f"REPARSE_POINT_FORBIDDEN:{current}")
        try:
            observed = current.stat()
        except OSError as error:
            raise PathSafetyError(f"PATH_METADATA_UNREADABLE:{current}") from error
        identities.append(
            (str(current), observed.st_dev, observed.st_ino, observed.st_mode)
        )
    return tuple(identities)


def _require_ancestor_identity(
    expected: tuple[tuple[str, int, int, int], ...], path: str | Path
) -> None:
    if _ancestor_identity_snapshot(path, include_target=True) != expected:
        raise PathSafetyError("PATH_ANCESTOR_IDENTITY_DRIFT")


def absolute_physical_path(
    path_value: str | Path,
    label: str = "PATH",
    *,
    strict: bool = False,
) -> Path:
    """Resolve one native absolute path after rejecting ambiguous aliases/reparse."""
    candidate = _validate_native_absolute(path_value, label)
    assert_safe_ancestors(candidate, include_target=True)
    try:
        resolved = candidate.resolve(strict=strict)
    except FileNotFoundError as error:
        raise PathSafetyError(f"PHYSICAL_PATH_MISSING:{label}") from error
    except OSError as error:
        raise PathSafetyError(f"PHYSICAL_PATH_INVALID:{label}") from error
    assert_safe_ancestors(resolved, include_target=True)
    return resolved


def confine_path(
    path_value: str | Path,
    allowed_root: str | Path,
    *,
    label: str = "PATH",
    strict: bool = False,
) -> Path:
    """Return a physical path only when it remains inside a regular allowed root."""
    root = absolute_physical_path(allowed_root, f"{label}_ROOT", strict=True)
    if not root.is_dir() or _is_reparse_point(root):
        raise PathSafetyError(f"ROOT_NOT_REGULAR_DIRECTORY:{label}")
    target = absolute_physical_path(path_value, label, strict=strict)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise PathSafetyError(f"PATH_OUTSIDE_ALLOWLIST:{label}") from error
    return target


def _mkdirs_safe(directory: Path, allowed_root: Path | None = None) -> None:
    directory = _validate_native_absolute(directory, "OUTPUT_PARENT")
    assert_safe_ancestors(directory, include_target=True)
    if allowed_root is not None:
        root = absolute_physical_path(allowed_root, "OUTPUT_ROOT", strict=True)
        try:
            directory.resolve(strict=False).relative_to(root)
        except ValueError as error:
            raise PathSafetyError("PATH_OUTSIDE_ALLOWLIST:OUTPUT") from error
    else:
        root = Path(directory.anchor)
    relative = directory.resolve(strict=False).relative_to(root.resolve(strict=True))
    current = root.resolve(strict=True)
    for part in relative.parts:
        current = current / part
        try:
            current.mkdir()
        except FileExistsError:
            pass
        if not current.is_dir() or _is_reparse_point(current):
            raise PathSafetyError(f"OUTPUT_PARENT_NOT_REGULAR_DIRECTORY:{current}")


def read_bound_bytes(
    path: str | Path,
    *,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
    allowed_roots: Iterable[str | Path] | None = None,
    label: str = "BOUND_FILE",
) -> tuple[bytes, Path]:
    """Read one regular file once and reject handle/path identity or byte drift."""
    target = absolute_physical_path(path, label, strict=True)
    if allowed_roots is not None:
        roots = [absolute_physical_path(root, f"{label}_ROOT", strict=True) for root in allowed_roots]
        if not any(target == root or target.is_relative_to(root) for root in roots):
            raise PathSafetyError(f"PATH_OUTSIDE_ALLOWLIST:{label}")
    if not target.is_file() or _is_reparse_point(target):
        raise PathSafetyError(f"NOT_REGULAR_FILE:{label}")
    ancestor_identity = _ancestor_identity_snapshot(target.parent, include_target=True)
    try:
        with target.open("rb") as handle:
            before = os.fstat(handle.fileno())
            data = handle.read()
            after = os.fstat(handle.fileno())
        path_after = target.stat()
    except OSError as error:
        raise PathSafetyError(f"BOUND_READ_FAILED:{label}") from error
    if not os.path.samestat(before, after) or not os.path.samestat(after, path_after):
        raise PathSafetyError(f"PATH_TOCTOU_DRIFT:{label}")
    _require_ancestor_identity(ancestor_identity, target.parent)
    if before.st_size != len(data) or after.st_size != len(data):
        raise PathSafetyError(f"PATH_TOCTOU_DRIFT:{label}")
    if expected_bytes is not None and len(data) != expected_bytes:
        raise PathSafetyError(f"BYTE_COUNT_MISMATCH:{label}")
    observed_sha256 = sha256_bytes(data)
    if expected_sha256 is not None and observed_sha256 != expected_sha256.upper():
        raise PathSafetyError(f"SHA256_MISMATCH:{label}")
    return data, target


def file_record(path: str | Path, root: str | Path | None = None) -> dict[str, Any]:
    allowed = [root] if root is not None else None
    data, target = read_bound_bytes(path, allowed_roots=allowed, label="FILE_RECORD")
    label = target.relative_to(absolute_physical_path(root, "FILE_RECORD_ROOT", strict=True)).as_posix() if root else str(target)
    return {"path": label, "bytes": len(data), "sha256": sha256_bytes(data)}


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    target = _validate_native_absolute(path, "ATOMIC_OUTPUT")
    _mkdirs_safe(target.parent)
    assert_safe_ancestors(target, include_target=True)
    if (target.exists() or target.is_symlink()) and _is_reparse_point(target):
        raise PathSafetyError(f"REPARSE_POINT_FORBIDDEN:{target}")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        assert_safe_ancestors(target, include_target=True)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_once_bytes(
    path: str | Path,
    data: bytes,
    *,
    allowed_root: str | Path | None = None,
) -> str:
    """Publish complete bytes atomically without overwriting an existing target."""
    target = _validate_native_absolute(path, "CREATE_ONCE_OUTPUT")
    root = absolute_physical_path(allowed_root, "CREATE_ONCE_ROOT", strict=True) if allowed_root is not None else None
    _mkdirs_safe(target.parent, root)
    if root is not None:
        target = confine_path(target, root, label="CREATE_ONCE_OUTPUT", strict=False)
    else:
        target = absolute_physical_path(target, "CREATE_ONCE_OUTPUT", strict=False)
    expected = sha256_bytes(data)
    ancestor_identity = _ancestor_identity_snapshot(target.parent, include_target=True)
    if target.exists() or target.is_symlink():
        observed, _ = read_bound_bytes(target, label="CREATE_ONCE_EXISTING")
        observed_sha256 = sha256_bytes(observed)
        if observed_sha256 != expected:
            raise RuntimeError(f"CREATE_ONCE_COLLISION:{target}:{observed_sha256}:{expected}")
        return "ALREADY_PRESENT_IDENTICAL"

    # A deterministic shared staging name lets one writer delete another writer's
    # in-flight inode.  A per-writer O_EXCL staging file preserves create-once
    # semantics while making identical concurrent writers independent.
    fd, staging_name = tempfile.mkstemp(
        prefix=f".{target.name}.pending.", dir=str(target.parent)
    )
    staging = Path(staging_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # Preserve the uniquely named partial file for explicit byte-bound recovery.
        raise
    try:
        staged, _ = read_bound_bytes(
            staging,
            expected_bytes=len(data),
            expected_sha256=expected,
            allowed_roots=[root] if root is not None else None,
            label="CREATE_ONCE_STAGING",
        )
        if staged != data:
            raise RuntimeError("ORPHAN_SIDE_EFFECT_DETECTED")
        _require_ancestor_identity(ancestor_identity, target.parent)
        assert_safe_ancestors(target, include_target=True)
        try:
            os.link(staging, target)
            created = True
        except FileExistsError:
            created = False
        if created:
            try:
                staged_stat = staging.stat()
                published_stat = target.stat()
            except OSError as error:
                raise PathSafetyError(f"CREATE_ONCE_IDENTITY_UNREADABLE:{target}") from error
            if not os.path.samestat(staged_stat, published_stat):
                raise PathSafetyError(f"CREATE_ONCE_IDENTITY_DRIFT:{target}")
        # Once our unique staging inode has been verified, a divergent winner is
        # a resolved CAS loss, not a crash orphan.  Read without an expected size
        # so a different-length winner is classified as the same collision.
        observed, _ = read_bound_bytes(target, label="CREATE_ONCE_READBACK")
        observed_sha256 = sha256_bytes(observed)
        if observed_sha256 != expected:
            # `staging` was created with O_EXCL by this invocation and its exact
            # bytes were verified above.  Removing it cannot touch the winner or
            # another writer's uniquely named staging file.
            try:
                staging.unlink(missing_ok=True)
            except OSError as error:
                raise PathSafetyError(
                    "CREATE_ONCE_LOSER_STAGING_CLEANUP_FAILED"
                ) from error
            raise RuntimeError(f"CREATE_ONCE_COLLISION:{target}:{observed_sha256}:{expected}")
        _require_ancestor_identity(ancestor_identity, target.parent)
        try:
            staging.unlink(missing_ok=True)
        except OSError as error:
            raise PathSafetyError("CREATE_ONCE_STAGING_CLEANUP_FAILED") from error
        return "CREATED" if created else "ALREADY_PRESENT_IDENTICAL"
    except BaseException:
        # Never silently delete a mismatching or partial crash artefact.
        raise


def recover_create_once_orphans(
    path: str | Path,
    data: bytes,
    *,
    allowed_root: str | Path | None = None,
) -> str:
    """Recover only byte-identical per-writer staging files for one exact target.

    Recovery is deliberately explicit.  It never guesses content, never accepts a
    mismatching orphan, and never overwrites an existing target.  Callers must first
    quiesce normal writers for the target.
    """
    target = _validate_native_absolute(path, "CREATE_ONCE_RECOVERY_OUTPUT")
    root = (
        absolute_physical_path(allowed_root, "CREATE_ONCE_RECOVERY_ROOT", strict=True)
        if allowed_root is not None
        else None
    )
    _mkdirs_safe(target.parent, root)
    if root is not None:
        target = confine_path(
            target, root, label="CREATE_ONCE_RECOVERY_OUTPUT", strict=False
        )
    else:
        target = absolute_physical_path(
            target, "CREATE_ONCE_RECOVERY_OUTPUT", strict=False
        )
    expected = sha256_bytes(data)
    prefix = f".{target.name}.pending."
    candidates = sorted(
        item
        for item in target.parent.iterdir()
        if item.name.startswith(prefix)
    )
    verified: list[Path] = []
    for candidate in candidates:
        try:
            staged, physical = read_bound_bytes(
                candidate,
                expected_bytes=len(data),
                expected_sha256=expected,
                allowed_roots=[root] if root is not None else None,
                label="CREATE_ONCE_RECOVERY_ORPHAN",
            )
        except (OSError, PathSafetyError) as error:
            raise RuntimeError("ORPHAN_SIDE_EFFECT_DETECTED") from error
        if staged != data:
            raise RuntimeError("ORPHAN_SIDE_EFFECT_DETECTED")
        verified.append(physical)

    if target.exists() or target.is_symlink():
        observed, _ = read_bound_bytes(
            target,
            expected_bytes=len(data),
            expected_sha256=expected,
            allowed_roots=[root] if root is not None else None,
            label="CREATE_ONCE_RECOVERY_EXISTING",
        )
        if observed != data:
            raise RuntimeError("ORPHAN_SIDE_EFFECT_DETECTED")
        status = "ALREADY_PRESENT_IDENTICAL"
    else:
        if not verified:
            raise RuntimeError("ORPHAN_RECOVERY_NOT_FOUND")
        ancestor_identity = _ancestor_identity_snapshot(
            target.parent, include_target=True
        )
        _require_ancestor_identity(ancestor_identity, target.parent)
        assert_safe_ancestors(target, include_target=True)
        try:
            os.link(verified[0], target)
        except FileExistsError:
            observed, _ = read_bound_bytes(
                target,
                expected_bytes=len(data),
                expected_sha256=expected,
                allowed_roots=[root] if root is not None else None,
                label="CREATE_ONCE_RECOVERY_RACE",
            )
            if observed != data:
                raise RuntimeError("ORPHAN_SIDE_EFFECT_DETECTED")
            status = "ALREADY_PRESENT_IDENTICAL"
        else:
            status = "RECOVERED"
        observed, _ = read_bound_bytes(
            target,
            expected_bytes=len(data),
            expected_sha256=expected,
            allowed_roots=[root] if root is not None else None,
            label="CREATE_ONCE_RECOVERY_READBACK",
        )
        if observed != data:
            raise RuntimeError("ORPHAN_SIDE_EFFECT_DETECTED")

    for candidate in verified:
        try:
            candidate.unlink(missing_ok=True)
        except OSError as error:
            raise PathSafetyError("CREATE_ONCE_STAGING_CLEANUP_FAILED") from error
    return status


def create_once_bytes_bound(path: str | Path, data: bytes, allowed_root: str | Path) -> str:
    return create_once_bytes(path, data, allowed_root=allowed_root)


def create_once_text(
    path: str | Path,
    text: str,
    encoding: str = "utf-8",
    *,
    allowed_root: str | Path | None = None,
) -> str:
    return create_once_bytes(path, text.encode(encoding), allowed_root=allowed_root)


def freeze_manifest(paths: Iterable[str | Path], root: str | Path, *, reject_extra_files: bool = True) -> dict[str, Any]:
    base = Path(root).resolve()
    resolved = sorted({Path(path).resolve() for path in paths}, key=lambda path: path.relative_to(base).as_posix())
    records = [file_record(path, base) for path in resolved]
    tree = sha256_bytes(canonical_json(records).encode("utf-8"))
    return {
        "schema": "omni-freeze-manifest-v2", "root": str(base),
        "tree_algorithm": TREE_ALGORITHM, "reject_extra_files": reject_extra_files,
        "files": records, "tree_sha256": tree,
    }


def verify_manifest(manifest: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    if manifest.get("schema") != "omni-freeze-manifest-v2":
        mismatches.append("MANIFEST_SCHEMA_INVALID")
    if manifest.get("tree_algorithm") != TREE_ALGORITHM:
        mismatches.append("TREE_ALGORITHM_INVALID")
    try:
        root = Path(manifest["root"]).resolve()
        expected_files = manifest["files"]
    except (KeyError, TypeError):
        return sorted(set([*mismatches, "MANIFEST_SHAPE_INVALID"]))
    expected_paths = {record.get("path") for record in expected_files if isinstance(record, dict)}
    if None in expected_paths or len(expected_paths) != len(expected_files):
        mismatches.append("MANIFEST_FILE_IDENTITY_INVALID")
    for expected in manifest["files"]:
        target = root / expected["path"]
        if not target.is_file():
            mismatches.append(f"MISSING:{expected['path']}")
            continue
        observed = file_record(target, root)
        if observed != expected:
            mismatches.append(f"DRIFT:{expected['path']}")
    observed_tree = sha256_bytes(canonical_json(manifest["files"]).encode("utf-8"))
    if observed_tree != manifest["tree_sha256"]:
        mismatches.append("MANIFEST_TREE_DIGEST_INVALID")
    if manifest.get("reject_extra_files") is True:
        observed_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
        for extra in sorted(observed_paths - expected_paths):
            mismatches.append(f"EXTRA:{extra}")
    elif manifest.get("reject_extra_files") is not False:
        mismatches.append("REJECT_EXTRA_FILES_NOT_BOOLEAN")
    return sorted(set(mismatches))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicit byte-bound recovery for one create-once target."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    recover = subparsers.add_parser("recover-create-once")
    recover.add_argument("--target", required=True, type=Path)
    recover.add_argument("--source", required=True, type=Path)
    recover.add_argument("--source-sha256", required=True)
    recover.add_argument("--allowed-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        source, _ = read_bound_bytes(
            args.source,
            expected_sha256=args.source_sha256.upper(),
            allowed_roots=[args.allowed_root],
            label="RECOVERY_SOURCE",
        )
        status = recover_create_once_orphans(
            args.target, source, allowed_root=args.allowed_root
        )
        print(canonical_json({"status": "PASS", "recovery_status": status}))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        reason = str(error).split(":", 1)[0] or type(error).__name__
        print(
            canonical_json(
                {"status": "BLOCKED", "reason_code": reason, "detail": str(error)}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
