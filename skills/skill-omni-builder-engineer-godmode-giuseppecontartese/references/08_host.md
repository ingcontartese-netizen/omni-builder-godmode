# Host capabilities, adapters, and profile parity

## Four independent capability fields

For every verb record:

- `documented`: primary documentation currently states it;
- `observed`: this exact host/version exposed or executed it;
- `authorized`: the current envelope permits it;
- `live_proven`: a bounded exercise produced readback evidence.

Never promote one field into another. Pin host, every runtime version that participates in the surface, model, reasoning effort, permissions, project root, tools, session ID, and access date. A desktop package, its embedded agent binary, and a same-named binary on `PATH` are distinct evidence subjects.

## Three levels

1. **Session carrier:** start, resume, fork, read/list, or continue a session.
2. **Supervisor:** dispatch, monitor, attach, respawn, schedule, or coordinate work.
3. **UI navigation:** make a selected task visibly active.

A level-1 pass does not prove level 2 or 3. UI navigation never grants execution ownership.

## Current primary-source snapshot (accessed 2026-07-30)

- **Codex:** the official skills manual documents user skills at `$HOME/.agents/skills`, repository skills in `.agents/skills` from CWD through the repository root, and `agents/openai.yaml`. This package sets `policy.allow_implicit_invocation: true` only to permit model-selected loading for explicit natural-language requests and motivated proposals; Station 0 still decides activation. The host may also expose native task/thread create, fork, read/list, send/wait, navigate, compact, goal, and automation surfaces. Each runtime verb and every model/reasoning restoration still needs local evidence. Sources: `https://learn.chatgpt.com/docs/build-skills.md`, `https://developers.openai.com/codex/app-server/`.
- **Claude Code:** official docs place personal skills at `~/.claude/skills/<skill-name>/SKILL.md` and project skills at `.claude/skills/<skill-name>/SKILL.md`; `disable-model-invocation: true` prevents model-selected invocation. The CLI documents `--resume`, `--continue`, `--model`, JSON output, and bounded print turns; a locally exposed `--fork-session` is separate runtime evidence and never proves supervisor or UI control. Sources: `https://code.claude.com/docs/en/slash-commands`, `https://code.claude.com/docs/en/cli-reference`.
- **Antigravity:** current official Google codelabs document skill packaging and discovery at global `~/.gemini/config/skills/` and project `.agents/skills/`. They do not establish a session-rotation carrier, agent switching, UI selection, or lease transfer. A separate Antigravity CLI path may differ and must be probed on the exact installed version before installation. Sources: `https://codelabs.developers.google.com/getting-started-with-antigravity-skills`, `https://codelabs.developers.google.com/getting-started-agy-ide`.
- **Cursor:** official CLI docs expose `ls`, `resume`, `--resume`, `--model`, print mode, and background agents; official IDE docs expose chat history and project rules. They do not prove that IDE and CLI share a session identifier or that Cursor consumes this Skill package format. Never pass an IDE chat ID to CLI resume without a future documented compatibility guarantee. Sources: `https://docs.cursor.com/en/cli/overview`, `https://docs.cursor.com/en/agent/chat/history`, `https://docs.cursor.com/context/rules-for-ai`.
- **Cowork:** keep unqualified unless current primary documentation and local runtime evidence establish the required carrier, supervisor, and UI verbs.

## Profile restoration

Capture a `surface_profile` before handoff and compare it after ATTACH, RESTORE, and RESUME:

`host/runtime_version_tuple + surface_id + model + effort_ui_label + effort_runtime_key + permission_mode + sandbox + project_root + tools/plugins/MCP + objective + automations + agentic_sentinel + script_sentinel + context_sentinel + native_session_id`.

Exact equality yields `PROFILE_PARITY_PASS`. A documented but unavailable model may use an explicitly approved compatibility mapping; otherwise declare `PROFILE_DEGRADED`, reduce authority, and stop before ownership transfer.

Never infer that a UI effort label and a runtime metadata key are equivalent. Record both verbatim and bind an explicit, host-version-specific mapping only after readback. If the UI says `Ultra` while runtime metadata reports `xhigh`, preserve both values and classify parity as `UNRESOLVED_MAPPING` until the adapter proves the mapping; do not silently normalize either side.

## Host-specific rule

Codex may use native task creation/forking for routine continuity when proven. Claude Code should normally rely on native compaction for daily continuity and use a distinct-session rotation as an emergency/tested belt with an external authorized operator. Antigravity and Cursor require adapter-specific proof; never copy Codex conclusions across hosts.

## Delivery invocation barrier

Host packaging must preserve the same three-level doctrine even where discovery differs:

- availability of metadata is `KNOWLEDGE_AVAILABLE` only;
- `OMNI_AWARE` may advise without opening state or effects;
- `OMNI_MODULE` and `OMNI_FULL` require explicit current-task invocation or explicit acceptance;
- an effect still requires its own exact authority after invocation.

For Codex, permit model-selected loading in `agents/openai.yaml`; for Claude Code, keep `disable-model-invocation` absent or false. These are discovery and reachability settings, never activation or effect authority. In every host the canonical Station 0 refusal remains authoritative after loading. For Antigravity, whose cited packaging guide does not document an equivalent switch, classify automatic discovery as availability only. None of these packaging measures proves discovery until a separately authorized post-install test runs.
