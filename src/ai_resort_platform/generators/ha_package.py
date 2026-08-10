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

    `children` are media_player entity_ids the `universal` platform falls
    back to for any command it has no entry for in `commands`, and for any
    attribute not listed in `attributes`. That fallback is the point: a
    child that already speaks the media protocol properly supplies artwork,
    artist and album - things a KNX bus cannot carry at all - while the
    KNX-backed commands here keep control of the physical amplifier.
    """

    unique_id: str
    name: str
    commands: dict[str, dict[str, object]] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    state_template: str | None = None
    children: tuple[str, ...] = field(default_factory=tuple)


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
class RoomArea:
    """One ETS room's entities, with its place in ETS's Building ->
    BuildingPart -> Floor -> Room location tree - see
    HomeAssistantPackage.areas for what this is (and isn't) used for.

    `room_id` is the ETS room's own id (ets.rooms.Room.id) - stable and
    unique per project, used to derive a collision-free per-room
    dashboard view id (see generators/ha_yaml.py's `path`) independent of
    whether the room's display name happens to match the villa's own
    name.

    `floor`/`building` are Room's own denormalized names for the
    enclosing Floor/BuildingPart it's nested under (ets.rooms.Room.floor/
    .building) - the authoritative answer for where THIS room sits in
    the tree, straight from ETS's location data; not cross-referenced
    against ETSProject.floors/.buildings (those are a separate catalog of
    top-level location nodes, not needed to resolve one room's own
    place in the tree).
    """

    room_id: str
    room: str
    floor: str | None
    building: str | None
    entity_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class HaSelect:
    """One Home Assistant KNX `select` entity - a named list of payloads.

    Its own dataclass rather than an HaEntity for the same reason HaScene
    is: `options` is not a group address, and HaEntity.config is a flat
    address map by design.

    Each option carries its payload explicitly, as (name, payload). An
    earlier version derived the payload from the option's position, which
    was wrong for the first device that used it - the BAB Audio Module
    numbers its equalizer profiles from 1, not 0. A device's payloads are
    defined by that device, so they are stated rather than inferred.

    `payload_length` is in bytes (1 for EIS14).
    """

    unique_id: str
    name: str
    address: str
    options: tuple[tuple[str, int], ...]
    state_address: str | None = None
    payload_length: int = 1


@dataclass(frozen=True, slots=True)
class HomeAssistantPackage:
    """Everything generated for one villa, merged as a single HA `packages/` file.

    `areas` is one RoomArea per ETS room, each holding the entity_ids
    wired to a device in that room plus that room's Building/Floor
    context - NOT real Home Assistant Areas: Home Assistant has no YAML
    mechanism to create an Area or assign an entity to one, for any
    integration (verified against official docs and HA maintainer
    commentary - it's a UI/runtime-only registry, full stop). This is
    used only to organize build_dashboard's per-room views; it is never
    serialized into the KNX package YAML itself.
    """

    villa_id: str
    villa_name: str
    entities: tuple[HaEntity, ...] = field(default_factory=tuple)
    scenes: tuple[HaScene, ...] = field(default_factory=tuple)
    selects: tuple[HaSelect, ...] = field(default_factory=tuple)
    scripts: tuple[HaScript, ...] = field(default_factory=tuple)
    media_players: tuple[HaMediaPlayer, ...] = field(default_factory=tuple)
    template_sensors: tuple[HaTemplateSensor, ...] = field(default_factory=tuple)
    automations: tuple[HaAutomation, ...] = field(default_factory=tuple)
    areas: tuple[RoomArea, ...] = field(default_factory=tuple)


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
    """`view_id` is the Lovelace view's own unique `path` (home-assistant.
    io/dashboards/views/) - distinct from `title`, which is free to
    collide with another view's title (e.g. a villa-wide view and a
    room view can both display "Villa A1") since Lovelace disambiguates
    views by `path`, not by title. Left as "" (omitted from the
    generated YAML - see generators/ha_yaml.py) for callers that don't
    need a stable id of their own.
    """

    title: str
    cards: tuple[DashboardCard, ...] = field(default_factory=tuple)
    view_id: str = ""


@dataclass(frozen=True, slots=True)
class Dashboard:
    """A single-view Lovelace dashboard for one villa."""

    villa_id: str
    title: str
    views: tuple[DashboardView, ...] = field(default_factory=tuple)
