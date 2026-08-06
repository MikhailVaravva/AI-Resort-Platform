# AI Resort Platform

Generates and manages KNX villa resort installations from a single reference
project, keyed off one ETS reference villa as the sole source of truth.

**Status:** foundation only — project structure, tooling and CI. No business
logic implemented yet.

## Concept

```
Reference Villa (.knxproj) -> Digital Twin -> Clone Engine -> Deployment
```

- **Reference Villa** — one finished, verified ETS project for a single
  villa. The only source of truth.
- **Digital Twin** — an in-memory, typed model of that villa.
- **Clone Engine** — produces new villas from the digital twin.
- **Deployment** — generates the artifacts (KNX projects, integrations)
  needed to actually deploy a cloned villa.

None of these stages are implemented yet; this repository currently
contains only the project skeleton they will be built into.

## Project layout

```
src/ai_resort_platform/
├── core/            # shared, format-agnostic building blocks
├── models/           # the internal domain model
├── readers/           # input format readers (e.g. .knxproj)
├── digital_twin/       # the reference villa's typed representation
├── clone_engine/        # villa cloning logic
├── generators/            # output/deployment artifact generation
├── integrations/           # third-party system integrations
└── cli.py                   # `ai-resort-platform` entry point
tests/
docs/
examples/
└── Reference-Villa/          # the reference ETS project (not yet added)
pyproject.toml
```

Every package above is currently empty except for its `__init__.py` — they
exist as the agreed structure, not as a promise of what's inside them yet.

This repository root also hosts an unrelated self-hosted infrastructure
stack (`docker-compose.yml`, `homeassistant/`, `grafana/`, `influxdb/`,
`mosquitto/`, `nodered/`, `ollama/`, `openwebui/`) — pre-existing, not part
of AI Resort Platform, left untouched by this project's tooling.

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
mypy src                  # type check
pytest                    # tests
```

(This repository root also hosts an unrelated infrastructure stack — see
[Project layout](#project-layout) — so lint/format commands are scoped to
`src`/`tests` explicitly rather than the whole repo root.)

CI (`.github/workflows/ci.yml`) runs all four on every push and pull request
against `main`.

## Status

Foundation commit only. No readers, no digital twin, no clone engine yet —
those will be built incrementally, each in its own reviewed step.
