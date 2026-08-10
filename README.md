# AI Resort Platform

Generates a Home Assistant configuration (entities, dashboard, automations)
directly from a real ETS project for a KNX villa, and is building, in
parallel, the machinery to write changes back into that same `.knxproj`.

**Status, 2026-08-10:** not a foundation-only skeleton. The Home Assistant
generator is deployed and running against a real, occupied villa (see
[Deployments](#deployments)) and has been corrected repeatedly against that
live installation's own bus traffic. The ETS-writing side is a separate,
newer effort, still partial. See [Two tracks](#two-tracks) below — this
project actually has two of them, not one linear pipeline.

## Two tracks

### Track A — ETS project → Home Assistant

```
ETSProject (.knxproj, via xknxproject)
  -> homeassistant/builder.py
  -> generators/ha_package.py + ha_yaml.py
  -> packages/<villa>.yaml + <villa>_dashboard.yaml
```

Reads a real `.knxproj` and generates entities, a BAB AUDIOMODULE V3 media
player, per-room dashboard views (from ETS's own Building/Floor/Room
hierarchy), and check-in/check-out automations. Mature and tested — see
[Deployments](#deployments) for what's actually running.

**Governing principle:** `ETSProject` is the single source of truth for
group addresses, DPTs and names — nothing is invented, nothing is parsed
from `.knxproj` by hand. In practice the ETS project has also turned out to
be an *incomplete* description of a real installation (some BAB module
functions are configured through the module's own web interface and were
never present in the exported project at all) — the rule stays "don't
invent," not "the project always has everything"; addresses confirmed
directly from a device get a named, explicit input rather than a guess.

### Track B — Reference Villa → Digital Twin → Clone Engine → ETS Writer

```
readers/jsonld_reader.py -> models/project.py (ProjectModel)
  -> digital_twin/ -> clone_engine/ -> generators/ets/ (ETS Writer)
```

A separate effort to read and eventually *write* a `.knxproj`, so a villa
can be cloned rather than hand-built in ETS. Uses a different model
(`ProjectModel`, from ETS's JSON-LD Semantic Export) than Track A's
`ETSProject`, and the two are not connected. Status: reading works
(`ProjectDiffer`, `SequentialIdentityStrategy` implemented and tested
against real project data); `EtsSerializer`/`EtsWriter` — actually writing
a change back into a `.knxproj` — are still interfaces only
(`NotImplementedError`). See `docs/ets-writer-architecture.md`.

## Quick start

```bash
pip install -e ".[dev]"

# Build a villa's Home Assistant package + dashboard from a deployment recipe:
ai-resort-platform build deployments/villa_a1.toml
```

A deployment recipe (`deployments/*.toml`) is the committed, explicit
record of everything a villa's generation depends on beyond the ETS
project itself — check-in playlist indices, the media source that
supplies what KNX can't carry, which addresses to stop polling. See
`deployments/villa_a1.toml` for the real one, with comments on why each
option is there.

## Deployments

`deployments/villa_a1.toml` builds the actual audio module + villa
configuration currently running on a real installation, from
`examples/Villa-A1/villa_a1.knxproj` (the installation's own exported ETS
project — distinct from `examples/Reference-Villa/`, an older project used
for the general-purpose entity/dashboard tests). The generated output is
deployed to that installation's Home Assistant.

**This means commands that touch the real deployment are not sandboxed.**
`GroupValueWrite` on a real address is a physical action in an actual home
(e.g. turning off a real amplifier). Reading (`GroupValueRead`, watching
logs, Home Assistant's Developer Tools states) is safe; anything that
writes to the bus needs the installation owner's explicit go-ahead first.

## Project layout

```
src/ai_resort_platform/
├── ets/                 # ETSProject - reads .knxproj via xknxproject (Track A)
├── homeassistant/        # builder.py - entities/media_player/areas/dashboard/automations
├── generators/
│   ├── ha_package.py       # HA output data model
│   ├── ha_yaml.py           # ...serialized to HA packages/dashboard YAML
│   └── ets/                  # ETS Writer (Track B): differ, identity, writer, models
├── readers/              # jsonld_reader.py - JSON-LD Semantic Export -> ProjectModel (Track B)
├── models/                # ProjectModel (Track B)
├── digital_twin/            # ProjectModel -> DigitalTwin (Track B)
├── clone_engine/              # villa cloning - design only, not implemented
├── deployment.py                 # deployment recipe (.toml) loader
├── core/, integrations/, ai/       # empty, reserved for future work
└── cli.py                           # `ai-resort-platform` entry point
deployments/           # committed deployment recipes (e.g. villa_a1.toml)
examples/
├── Reference-Villa/     # older reference project, used by the general test suite
└── Villa-A1/               # the real installation's own exported ETS project
docs/
└── ets-writer-architecture.md   # Track B design doc
tests/
pyproject.toml
```

This repository root also hosts an unrelated self-hosted infrastructure
stack (`docker-compose.yml`, `homeassistant/` — the local Home Assistant
sandbox/deployment target, `grafana/`, `influxdb/`, `mosquitto/`,
`nodered/`, `ollama/`, `openwebui/`) — not part of AI Resort Platform's own
source, left untouched by its tooling (`ruff`/`black`/`mypy` are scoped to
`src`/`tests` for exactly this reason).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

## Development workflow

```bash
ruff check src tests      # lint
black --check src tests   # format check
mypy src                  # type check (strict)
pytest                    # tests
```

CI (`.github/workflows/ci.yml`) runs all four on every push and pull
request against `main`.

Two things worth knowing if you're picking this repository up fresh:

- **Two AI sessions can be working on it at once**, one per track, sharing
  `main`. If you're an agent continuing this work: read
  `ОБЯЗАТЕЛЬНО_К_ПРОЧТЕНИЮ.md` and `ЗАДАНИЕ.md` in the repo root first —
  they carry live handoff notes between sessions and go stale within
  hours, faster than this file.
- `generators/ets/*` (Track B) and everything else (Track A +
  infrastructure) are, by convention between those sessions, worked on
  separately to avoid stepping on the same files.
