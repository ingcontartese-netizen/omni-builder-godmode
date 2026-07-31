# R3 relay ledger: one governed stream per physical writer

This module replaces file-per-message transport with one append-only logical stream per agent. It preserves the PM scaling rule without inventing a global file-spanning counter.

Read `scripts/relay_ledger.py` and `schemas/relay_ledger_entry.schema.json` before integrating the carrier.

## Scope and guarantee

The canonical source is UTF-8, no BOM, LF-only NDJSON. Each physical line is one complete canonical JSON entry. Markdown is payload, not framing.

The runtime proves:

- identity by `(run_id, stream_id, stream_seq)` plus a globally unique `event_id`;
- strict physical order and uniqueness within one stream;
- a full-entry SHA-256 chain binding metadata, payload, lease, fence, predecessor, and volume link;
- one active lease epoch and physical writer instance through the local broker API;
- append lock, exact-byte write, `fsync`, close/reopen readback, and event reconciliation;
- vector checkpoints across streams;
- exact-byte volume seals and create-new rotation automatically triggered by a
  bound entry threshold, byte threshold, or explicit phase gate;
- fail-closed torn-tail detection and exact-target repair only under caller-supplied authority.

It does **not** prove a total order across streams, trusted wall-clock time, independent authorship against a compromised local account, availability, recovery of deleted bytes, or that a caller-selected anchor directory is an independent trust domain. Every entry, seal, and checkpoint therefore says `LOCAL_HASH_CHAIN_UNANCHORED`. The runtime can create and verify an exact external vector-head anchor, but a second local path alone remains `UNQUALIFIED`. Production tamper evidence requires the caller to qualify and govern that path in an independent failure and credential domain, plus protected backups.

## Ordering and citations

`stream_seq` starts at 1 and increases across volume rotation. Two agents may both have sequence 1 because their `stream_id` differs. There is no `MAX(all files)+1`, parity allocator, or inference from timestamps.

Every entry carries `observed_heads`, a causal observation vector. Each object is exactly `{stream_id, stream_seq, entry_hash}`; stream IDs are unique and the list is sorted lexicographically by `stream_id`. It records which exact peer heads the writer had observed when constructing the request. It does not merge streams, allocate a global number, prove simultaneity, or create a total order. Missing, malformed, duplicate-stream, or unsorted observations block.

Stable citation:

```text
run_id / stream_id / stream_seq / entry_hash
```

If a product truly requires one cross-stream total order, route appends through a transactional sequencer. A derived display number is never an integrity key or checkpoint.

## Canonical hash

The only accepted canonicalization contract is `OMNI_CANONICAL_JSON_V1`, recorded in every entry as `canonicalization_version`. The writer NFC-normalizes text and converts CRLF/CR to LF before record construction. `body_bytes` is the exact byte length of that normalized body encoded as UTF-8; it is recomputed during every validation. The stored object permits strings, integers, booleans, null, arrays, and objects; floats, duplicate keys, BOM, non-UTF-8, noncanonical key order/spacing, a wrong body length, an unknown canonicalization version, and missing final LF fail closed.

```text
entry_hash =
  SHA-256(
    UTF8("OMNI-RELAY-ENTRY-V1\0")
    || canonical_json(entry_without_entry_hash)
  )
```

`prev_entry_hash` points to the preceding full `entry_hash`. The first entry alone uses null. The first entry of a rotated volume also binds the previous `seal_hash`.

`canonicalization_version`, `body_bytes`, and the complete sorted `observed_heads` vector are inside both the request fingerprint and the full entry hash. `request_hash` excludes allocation fields and creation time. Retrying the same `event_id` with the same causal request returns `RECONCILED`; changing its body encoding contract, byte length, or causal observations returns `EVENT_ID_CONFLICT`.

## Ownership, leases, and solo hats

Normal product code must not receive direct write access to ledger files. One narrow broker process owns the directory and calls this runtime. A lease receipt binds:

- run and stream;
- logical writer;
- physical writer instance;
- lease ID and expiry;
- monotonically increasing fencing epoch;
- topology and independence claim;
- exact caller-supplied authority digest.

A new writer requires a strictly higher fence. Appends from an old lease fail even if the old process survives. OS locking serializes cooperating processes, but locking alone is not authorization and cannot stop a process that can bypass the broker.

`SOLO_HATS` means one physical writer instance may alternate `BUILDER` and `VERIFIER` labels in one stream. It always records `independent_verifier=false`; a hat change is not independent verification. Two concurrent solo processes are illegal even when they claim different hats.

Lease activation authority is supplied by a human gate or deterministic policy broker. The Python object does not authenticate or mint that authority.

## Windows append and ambiguous effects

The stream lock is held from tail validation through append, `fsync`, reopen, and readback. The append handle uses end-of-file append mode and performs one `os.write`; a short write becomes `AMBIGUOUS_SHORT_APPEND` and leaves the stream blocked for inspection. Readback validates exact bytes, physical EOF, sequence, hashes, and event ID.

This is a local NTFS-oriented minimum, not a power-loss transaction. A crash may leave an incomplete final line. Do not use PowerShell `Add-Content`, seek-to-EOF followed by an unlocked write, a cloud-sync folder, or SMB as an equivalent primitive. Qualify each carrier separately. For stronger durability, use a transactional database/WAL as source of truth and render NDJSON/Markdown as derived artifacts.

After an unknown append result, call `reconcile(event_id, request_hash)` before retrying. A missing response is not evidence that no append occurred.

## Torn-tail recovery

An incomplete final physical line blocks validation, append, seal, rotation, and checkpoint advancement.

1. `inspect_torn_tail()` validates every complete predecessor and returns an exact plan: file hash/size, valid byte boundary, torn-fragment hash/size, repaired hash, and plan hash.
2. A human or policy broker returns `omni-relay-ledger-repair-authority-v1`, binding every plan field, action, authority identity, source, and expiry.
3. `repair_torn_tail()` writes an intent receipt, rechecks the exact bytes, truncates only the uncommitted fragment, calls `fsync`, reopens and verifies, writes a completion receipt, then revalidates the chain.

Never truncate behind a complete or sealed entry. An anchor or checkpoint behind the proposed boundary requires a separate incident path.

## Vector checkpoints

`write_vector_checkpoint()` records a sorted head for every input stream:

```text
stream_id, volume_id, volume_no, stream_seq, entry_hash, byte_offset
```

`verify_vector_checkpoint()` requires the old head to remain present and identical, then returns every higher entry per stream. A checkpoint is consumer state, not an external anchor. Advance it only after durable consumption; external effects use `event_id` as their idempotency key and must be reconciled before retry.

## External create-once anchors

`create_external_anchor()` writes a canonical full-record anchor to a root that must neither equal, contain, nor be contained by any ledger root. The file is created with `O_EXCL`, flushed, reopened, byte-compared, and revalidated. Anchor filenames carry a caller-supplied strictly monotonic sequence; each record binds `previous_anchor_hash`, so deletion, reordering, collision, and predecessor replacement fail closed.

The anchored vector is sorted by `stream_id`. Each head binds:

```text
ledger-root fingerprint
volume identity and number
stream sequence and full entry hash
physical end offset and exact prefix hash
sealed-volume hash when one existed at anchor time
```

The prefix hash remains verifiable when later entries are legitimately appended to the same active volume. A non-null seal hash must remain identical. `verify_external_anchor()` first validates the complete create-once anchor chain, then proves that each anchored record and volume prefix still exists in the local ledgers. A fully recomputed local chain therefore remains locally self-consistent but fails with `EXTERNAL_ANCHOR_HEAD_DIVERGENCE` or `EXTERNAL_ANCHOR_VOLUME_PREFIX_DIVERGENCE`.

Trust-domain status is separate from mechanical integrity:

- no caller qualification: `UNQUALIFIED` and verification returns `ANCHOR_VERIFIED_UNQUALIFIED`;
- exact caller attestation: `CALLER_QUALIFIED_UNVERIFIED` and verification returns `ANCHOR_VERIFIED_CALLER_QUALIFIED_UNVERIFIED`;
- `require_qualified=true` rejects an unqualified path.

`external_anchor_qualification_subject()` returns the exact root and stream fingerprints the caller must assess. A qualification binds a trust-domain ID, qualified actor, basis, evidence hash, timestamps, and expiry. The accepted bases are `SEPARATE_PRINCIPAL_APPEND_ONLY`, `WORM`, `TRANSPARENCY_LOG`, and `PROTECTED_REMOTE`. The runtime checks the binding and expiry but cannot prove the organizational controls or authenticate the caller; `CALLER_QUALIFIED_UNVERIFIED` is intentionally not an independent verifier verdict.

API:

```python
subject = external_anchor_qualification_subject(anchor_root, "RUN-ANCHORS", ledgers)
# A competent caller evaluates `subject` and may return a bound qualification.
created = create_external_anchor(
    anchor_root,
    "RUN-ANCHORS",
    1,
    ledgers,
    qualification=caller_qualification_or_none,
)
verified = verify_external_anchor(
    anchor_root,
    "RUN-ANCHORS",
    ledgers,
    anchor_seq=1,
    require_qualified=False,
)
```

CLI uses a JSON ledger specification containing `run_id` and a `streams` array with `root`, `stream_id`, `topology`, and `independent_verifier`:

```text
python -B scripts/relay_ledger.py anchor-create <anchor-root> <run-id> \
  --ledger-spec <spec.json> --anchor-set-id <id> --anchor-seq 1 \
  [--qualification <qualification.json>]

python -B scripts/relay_ledger.py anchor-verify <anchor-root> <run-id> \
  --ledger-spec <spec.json> --anchor-set-id <id> [--anchor-seq 1] \
  [--require-qualified]
```

The external root must enforce create-once retention independently. Copying anchors into a mutable sibling directory under the same account does not make that directory trustworthy.

## Rotation

Every `RelayLedger` has one per-writer `RotationPolicy`. The defaults are 1,000
entries or 8,388,608 exact NDJSON bytes per volume. Override them explicitly for
a qualified carrier:

```python
policy = RotationPolicy(
    max_entries_per_volume=500,
    max_bytes_per_volume=4_194_304,
)
ledger = RelayLedger(root, "RUN-1", "builder", rotation_policy=policy)
```

`append()` evaluates both limits after durable readback while it still owns the
stream lock. At least one reached limit calls the same create-once seal path
before returning. Its result always includes `rotation`: either
`ROTATION_NOT_TRIGGERED`, `ROTATED`, or `ROTATION_RECONCILED`. A retry of a
reconciled event does not append or allocate a second seal.

At a governed phase boundary call
`rotate_for_phase_gate(lease, "F3_TO_F4")`. The phase identifier, bound policy,
and exact sorted reasons are fields of the hash-protected volume seal. A retry
with the same gate reconciles the same create-once seal. Do not infer a gate from
timestamps or prose.

`seal_and_rotate()` remains the explicit manual escape hatch and records
`MANUAL_REQUEST`; it is not the threshold scheduler. All three paths hold the
same active lease and per-stream lock. A volume seal binds exact file bytes,
first/last sequence, entry count, head hash, predecessor seal, policy, trigger
reasons, and optional phase gate. The next filename is create-new; its first
entry continues both the entry and volume-seal chains. A sealed volume rejects
later append.

Rotation is strictly per writer. Thresholds never inspect peer streams, never
allocate a global sequence, and never turn causal `observed_heads` into a total
order.

The runtime recovers the bounded crash case “seal exists, next empty volume missing” by creating that successor. Two successors, a gap, an unsealed predecessor, a changed sealed volume, or an incorrect link block.

## Minimum use

```python
from relay_ledger import (
    Lease,
    RelayLedger,
    RotationPolicy,
    create_external_anchor,
    external_anchor_qualification_subject,
    verify_external_anchor,
)

ledger = RelayLedger(root, "RUN-1", "builder")
lease = Lease("builder", "process-1", "LEASE-1", 1, "2099-01-01T00:00:00Z")

# `authority` must come from the caller's human/policy gate and bind this lease.
ledger.activate_lease(lease, authority)
result = ledger.append(
    lease,
    event_id="123e4567-e89b-42d3-a456-426614174000",
    title="Handoff",
    body="Payload",
    observed_heads=[
        {
            "stream_id": "verifier",
            "stream_seq": 7,
            "entry_hash": "<full SHA-256 of verifier entry 7>",
        }
    ],
)
```

## Required test families

- **POS:** two streams may each start at sequence 1; canonical schema, hash links, reconcile, vector checkpoint, seal, and rotation pass.
- **NEG:** metadata mutation, wrong predecessor, duplicate event, stale fence, wrong physical writer, append to a sealed volume, or divergent checkpoint blocks with no silent renumbering.
- **MALFORMED:** duplicate JSON keys, BOM, invalid UTF-8, noncanonical JSON, wrong types, missing final LF, incomplete line, and schema omission block.
- **CAUSAL:** the canonicalization version, normalized UTF-8 body length, and sorted unique causal vector are present and hash-bound; missing/wrong versions, wrong lengths, duplicate streams, unsorted lists, or malformed heads block.
- **RECOVERY:** failpoints before write, during a partial causal entry append, after write/before checkpoint, and at every seal/next-volume boundary preserve one known head; torn-tail repair requires exact authority and the next causal entry reuses a fully validated vector.
- **SOLO:** one writer may alternate hats with `independent_verifier=false`; a second writer or an independence claim blocks.
- **ANCHOR:** monotonic sequence, predecessor digest, O_EXCL collision, root overlap, vector binding, unqualified status, caller-attested qualification, and a fully recomputed local rewrite are tested. These tests prove the mechanism; operational trust remains pending until the caller qualifies the external credential and failure domain.
