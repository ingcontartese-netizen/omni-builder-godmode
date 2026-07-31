# Installation Guide

The skill installs as a plain directory — no build step. The optional validation scripts
need Python 3 plus two libraries (`pip install -r requirements.txt` inside the skill folder:
PyYAML and jsonschema). The skill itself needs nothing. One copy per host, verified in one command.

> **Rule of thumb:** wherever your host keeps its skills, this skill goes in a folder named
> `skill-omni-builder-engineer-godmode-giuseppecontartese` right next to the others.

## Claude Code / Claude Desktop (shared catalog)

```bash
git clone https://github.com/ingcontartese-netizen/omni-builder-godmode.git
cp -r omni-builder-godmode/skills/skill-omni-builder-engineer-godmode-giuseppecontartese ~/.claude/skills/
```

Verify:

```bash
cd ~/.claude/skills/skill-omni-builder-engineer-godmode-giuseppecontartese
pip install -r requirements.txt
python -B scripts/validate_skill.py . --no-tests
```

Expected: `"status": "PASS"`. Restart the app (or open a new session) so the catalog refreshes.

You can also upload the skill as an account capability: zip the skill folder and use
**Settings → Capabilities → Add** in the Claude desktop app.

## OpenAI Codex

Same copy, different target:

```
%USERPROFILE%\.agents\skills\skill-omni-builder-engineer-godmode-giuseppecontartese
```

Verify with `--host-projection codex`, then restart the Codex app (its catalog is built at
startup).

## Google Antigravity

```
%USERPROFILE%\.gemini\config\skills\skill-omni-builder-engineer-godmode-giuseppecontartese
```

Verify with `--host-projection antigravity`.

## Sanity checks after any install

| Check | Command | Expected |
|---|---|---|
| Structure + doctrine | `python -B scripts/validate_skill.py . --no-tests` | `PASS` |
| Full test suite | `python -B -m unittest discover -s tests` | `Ran 226 tests ... OK` |
| Invocation gate | `python -B scripts/sentry/mode_a_guard.py --turns 1` | `NO_SKILL_REQUIRED` |

The last check is the point of the whole design: with no explicit request, the skill
declines to activate. Installing it changes nothing until you call it.

## Uninstall

Delete the skill folder. The skill keeps no state outside the projects you used it in.
