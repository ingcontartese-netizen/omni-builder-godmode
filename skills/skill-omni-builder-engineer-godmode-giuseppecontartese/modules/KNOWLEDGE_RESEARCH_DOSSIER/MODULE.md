# KNOWLEDGE_RESEARCH_DOSSIER

`KNOWLEDGE_RESEARCH_DOSSIER` is a bounded `OMNI_MODULE` for one named topic
and one or more named local material files. It studies those files, maps the
web lightly, performs a deeper second research pass, produces a
provenance-bearing Markdown dossier, emits a typed module outcome, and stops.

The module is not an intake path. It does not create Q0, a project well, a
Team Card, lanes, a fused program, an Omni Mode, sentinels, or autonomy. It
does not convert an ordinary request into a module request. Activation must
name exactly this module.

## Authority boundary

Activation grants no effects. Before each effect, the host must present one
separate, create-once authority record:

| Effect | Required scope |
| --- | --- |
| `READ_NAMED_SOURCES` | Exact material files, each bound by absolute path, byte count, and SHA-256 |
| `CREATE_FILES` | Exact output root and exact paths that may be created |
| `NETWORK_RESEARCH` | Topic/run binding, HTTPS policy, and explicit query/source budgets |
| `DOWNLOAD` | Optional exact locators and a quarantined output root |

An authority record has exactly one action. Network authority never implies
download authority. Without a valid `DOWNLOAD` record, research continues as
`DOWNLOAD_NOT_AUTHORIZED_CAPTURE_MD_ONLY`; raw response bodies must not be
stored.

## Host procedure

1. Obtain an `OMNI_MODULE` activation receipt naming only
   `KNOWLEDGE_RESEARCH_DOSSIER`.
2. Gate `READ_NAMED_SOURCES`, read only the bound material files, and write
   `MATERIAL_STUDY.json`.
3. Gate `NETWORK_RESEARCH`, run a light discovery pass, preserve query and
   source captures as Markdown, and write `LIGHT_MAP.json`.
4. Freeze deep questions, priorities, and stop conditions. Run the deep pass,
   which must add at least one source not present in the light pass, and write
   `DEEP_RESEARCH_RECEIPT.json`.
5. If raw download is useful, gate a separate `DOWNLOAD` record first. Store
   permitted bytes only below `quarantine/`, hash them, record rights and scan
   evidence, and never execute them. Otherwise remain capture-only.
6. Build the cumulative `SOURCE_MANIFEST.json` and `DOSSIER.md`. Every
   substantial finding must cite stable source IDs, and each actually used
   source must be represented in the provenance section.
7. Run `run.py finalize`. It rechecks authorities, live file identities,
   record digests, the light/deep source delta, the cumulative source chain,
   captures, acquisitions, and dossier citations. It then creates
   `MODULE_OUTCOME.json` once.
8. Accept only `KNOWLEDGE_RESEARCH_DOSSIER_READY` with `next_gate: STOP`.

The host performs web browsing with its normal web tool. `run.py` never opens
the network; it is the deterministic authority, integrity, provenance, and
terminal-outcome boundary.

## Fixed output names

- `MATERIAL_STUDY.json`
- `LIGHT_MAP.json`
- `DEEP_RESEARCH_RECEIPT.json`
- `SOURCE_MANIFEST.json`
- `DOSSIER.md`
- `MODULE_OUTCOME.json`
- Markdown evidence below `captures/`
- Optional raw bytes and their evidence below `quarantine/`

## CLI

```text
python modules/KNOWLEDGE_RESEARCH_DOSSIER/run.py gate \
  --activation ACTIVATION.json --authority READ_AUTHORITY.json \
  --action READ_NAMED_SOURCES --topic "topic" --run-id RUN_001

python modules/KNOWLEDGE_RESEARCH_DOSSIER/run.py finalize \
  --activation ACTIVATION.json \
  --read-authority READ_AUTHORITY.json \
  --write-authority WRITE_AUTHORITY.json \
  --network-authority NETWORK_AUTHORITY.json \
  --topic "topic" --run-id RUN_001 --output-root OUTPUT_ROOT

python modules/KNOWLEDGE_RESEARCH_DOSSIER/run.py verify \
  --activation ACTIVATION.json \
  --read-authority READ_AUTHORITY.json \
  --write-authority WRITE_AUTHORITY.json \
  --network-authority NETWORK_AUTHORITY.json \
  --topic "topic" --run-id RUN_001 --output-root OUTPUT_ROOT
```

Add `--download-authority DOWNLOAD_AUTHORITY.json` only when that independent
authority exists. Commands return canonical JSON. Success exits `0`; a typed
stop exits `2`. Finalization is create-once: identical replay is accepted,
while divergent pre-existing output is `CREATE_ONCE_COLLISION`.
