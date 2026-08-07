from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class HaEntity:
    """One Home Assistant KNX-platform entity.

    `config` holds the KNX integration YAML keys for this domain (e.g.
    "address", "brightness_address") mapped to group addresses - kept as a
    plain dict rather than one dataclass per HA domain, since the KNX
    platform schema itself is just a flat set of address keys per domain.
    """

    domain: str
    unique_id: str
    name: str
    config: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HaScene:
    """One Home Assistant KNX `scene` entity (recalls a specific scene number)."""

    unique_id: str
    name: str
    address: str
    scene_number: int


@dataclass(frozen=True, slots=True)
class HaScript:
    """One Home Assistant `script` (a named, callable sequence of actions)."""

    unique_id: str
    name: str
    sequence: tuple[dict[str, object], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class HaMediaPlayer:
    """One Home Assistant `media_player`, built via the core `universal`
    platform (home-assistant.io/integrations/universal/) - the KNX
    integration has no native media_player platform, so this composes one
    entirely from other entities already in this package. `commands` maps
    a fixed set of documented command names (turn_on, media_play, ...) to
    a service-call dict (`action`/`target`/`data`, verbatim as `universal`
    expects); `attributes` maps a fixed set of documented media_player
    attribute names to `entity_id` (or `entity_id|attribute`) strings.
    `state_template` is the documented alternative to a plain
    `attributes["state"]` entity reference, for when the state depends on
    more than one entity (e.g. a power switch and a play/pause switch
    together deciding between off/idle/playing) - `universal` evaluates
    it itself, so it replaces `attributes["state"]` rather than
    complementing it.
    """

    unique_id: str
    name: str
    commands: dict[str, dict[str, object]] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    state_template: str | None = None


@dataclass(frozen=True, slots=True)
class HaTemplateSensor:
    """One Home Assistant `template` sensor (home-assistant.io/
    integrations/template/), for a value that has to be computed with
    Jinja - unlike `HaMediaPlayer.attributes`, which only accepts a bare
    entity/attribute reference and cannot do unit conversion itself.
    `state` must render to a number or `none`, per that platform's schema.
    """

    unique_id: str
    name: str
    state: str


@dataclass(frozen=True, slots=True)
class HaAutomation:
    """One Home Assistant `automation` (triggers -> actions).

    Field names match the current official automation schema
    (home-assistant.io/docs/automation/yaml/) - `triggers`/`actions`
    (plural), not the older singular `trigger`/`action` keys. Not derived
    from raw KNX wiring (there is no "when X then Y" signal in group
    addresses themselves): populated by generators that know a standard
    behavioural pattern independent of any one villa's data, e.g.
    homeassistant/builder.py:_build_welcome_automation.
    """

    unique_id: str
    name: str
    triggers: tuple[dict[str, object], ...] = field(default_factory=tuple)
    actions: tuple[dict[str, object], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class HomeAssistantPackage:
    """Everything generated for one villa, merged as a single HA `packages/` file."""

    villa_id: str
    villa_name: str
    entities: tuple[HaEntity, ...] = field(default_factory=tuple)
    scenes: tuple[HaScene, ...] = field(default_factory=tuple)
    scripts: tuple[HaScript, ...] = field(default_factory=tuple)
    media_players: tuple[HaMediaPlayer, ...] = field(default_factory=tuple)
    template_sensors: tuple[HaTemplateSensor, ...] = field(default_factory=tuple)
    automations: tuple[HaAutomation, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DashboardCard:
    """One Lovelace card.

    Two shapes, chosen by `card_type`: the default "entities" card lists
    multiple entities (`entities`); "media-control" (the documented card
    for a media_player entity) is a single-entity card (`entity`) instead.
    """

    title: str
    entities: tuple[str, ...] = field(default_factory=tuple)
    card_type: str = "entities"
    entity: str | None = None


@dataclass(frozen=True, slots=True)
class DashboardView:
    title: str
    cards: tuple[DashboardCard, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Dashboard:
    """A single-view Lovelace dashboard for one villa."""

    villa_id: str
    title: str
    views: tuple[DashboardView, ...] = field(default_factory=tuple)
