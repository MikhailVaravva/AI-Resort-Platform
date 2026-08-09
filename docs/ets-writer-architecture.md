# ETS Writer — architecture (Step 6, design only)

No writing is implemented in this step. Every interface below has a body of
`raise NotImplementedError`. This document explains *why* the architecture
is shaped the way it is, since several requirements (identity, GUIDs,
lossless round-trip) only make sense in light of one hard constraint stated
plainly here first.

## 0. The constraint this whole design is built around

**We have never opened a real `project.xml`.** Step 1 found the reference
`.knxproj`'s inner project archive (`P-035B.zip`) is AES-encrypted, never
got a working password, and Step 1's own review redirected the whole
Reader/ProjectModel/DigitalTwin pipeline to consume ETS's **Semantic
Export** (JSON-LD) instead — a real, official, but *different* ETS output
format from the internal project XML. Every field our `ProjectModel` and
`DigitalTwin` carry today came from that JSON-LD graph, not from
`project.xml`.

This means:

- We know KNX Association publishes a versioned "KNX XML Project Schema"
  (XSD) for `project.xml`, but only through KNX GitLab / Manufacturer Tool
  access we don't have — not something we can currently verify against.
- Object ids we carry (`GroupAddress.id`, `Device.id`, e.g. `"prj:GA-266"`,
  `"prj:DI-55"`) are the Semantic Export's node ids. They almost certainly
  correspond to `project.xml`'s real internal `Id` attributes (the naming
  pattern matches ETS's known `P-<projectId>-0_<LocalId>` convention
  observed elsewhere in the same archive), but this is an **assumption**,
  not something we've confirmed by reading both formats side by side.
- We do not know the exact XML element/attribute names, nesting, or
  whether `project.xml` is itself further checksummed or signed.

**Every "strategy" below is designed to be correct in shape without
depending on facts we don't have** — and every place a real fact is
required, it's flagged as an open risk in §18, not guessed at. The
alternative (guessing the schema and writing something that merely *looks*
plausible) would produce a Writer that appears to work and then corrupts a
real installation's project the first time ETS opens it. Given the earlier
false starts with password guessing on the reference project, this design
does not repeat that mistake.

## 1. Guiding principle: patch, don't regenerate

A `.knxproj` contains, alongside the project data we care about, tens of
megabytes of manufacturer-published catalog data (`M-XXXX/` folders — full
Hardware.xml/Catalog.xml/application-program XML per device family) and
KNX Association master data (`knx_master.xml`) — all of it read-only
reference data our platform has no authority to author. We are not a
device manufacturer or KNX Association; we cannot legitimately invent a
new product's application-program XML.

**Conclusion: the ETS Writer is an in-place editor of an existing
`.knxproj`, never a from-scratch generator.** It always starts from a base
project (the reference project, or a project the reference has already
been cloned into), computes the *minimal* set of changes, and patches only
what changed. Everything else — manufacturer folders, baggages/icons,
`knx_master.xml`, and any project data our `ProjectModel` doesn't capture
(see §12) — passes through byte-identical. This single principle is what
makes "Define validation rules", "lossless round-trip", and "preserve
everything not intentionally modified" all the same underlying design,
rather than three separate problems.

This mirrors the Clone Engine's own principle from Step 5: cloning always
starts from the Reference Villa, never from nothing. The ETS Writer is the
mechanism that makes a Clone Engine result (or any other edit) actually
land back in a real `.knxproj`.

## 2. Full data flow

```
                    ┌─────────────────────────────────────────────┐
                    │                  READ SIDE                    │
                    │                                                 │
  ETS Project  ───▶ JsonLdImporter ───▶ ProjectModel ───▶ build_resort ───▶ DigitalTwin
 (.knxproj /                                  │                              │
  Semantic Export)                            │                              ▼
                    │                          │                    HA / CubeVision / AI
                    └──────────────────────────┼─────────────────────────────┘
                                                │ (this ProjectModel is the
                                                │  "original" every diff is
                                                │  computed against)
                    ┌───────────────────────────┼─────────────────────────────┐
                    │                 WRITE SIDE  ▼                            │
                    │                                                          │
      DigitalTwin ──┼──▶ (reverse projection, │  ┌─▶ ProjectDiffer ──▶ ProjectChangeSet
     (rename/clone/  │     not built this step)▼  │        │
      edit ops)      │                 updated ProjectModel │        ▼
                    │                                       │  IdentityStrategy
      ProjectModel ──┼───────────────────────────────────────┘  (mints ids/addresses
    (direct edit)    │                                          for CREATE changes)
                    │                                                 │
                    │                                                 ▼
                    │                                          EtsSerializer
                    │                                        (ProjectChangeSet ->
                    │                                         SerializedProject)
                    │                                                 │
                    │                                                 ▼
                    │                                    EtsWriter.write(base_path,
                    │                                     change_set, output_path)
                    │                                          │
                    │                    Update Pipeline (§5) │
                    │                                          ▼
                    │                                   ETS Project (.knxproj)
                    └──────────────────────────────────────────────────────────┘
```

Two things to notice:

- **DigitalTwin is not a direct Writer input.** It's a lossy, heuristic
  view (see §16) — you can't serialize it back to ETS with confidence
  about what you're NOT changing. Anything coming from DigitalTwin (a
  clone, a rename made through the twin) must first become an *updated*
  `ProjectModel` — a reverse projection this step explicitly does not
  design (see §16) — before the Write Side pipeline can touch it.
- **`ProjectDiffer` needs the exact `ProjectModel` the Reader produced from
  the base file**, not a re-derived one, or the diff is meaningless: it's
  comparing against a model that might already disagree with the file on
  disk.

## 3. Writer interfaces (code)

`src/ai_resort_platform/generators/ets/models.py` and
`generators/ets/writer.py` contain the actual typed contracts. Summary:

- `ProjectDiffer.diff(original, updated) -> ProjectChangeSet` — §4.
- `IdentityStrategy.mint_id(object_kind, base_project) -> str` — §6.
- `EtsSerializer.serialize(change_set, base_project) -> SerializedProject` — §4.
- `EtsWriter.write(base_project_path, change_set, output_path) -> WriteResult` — §5, the single entry point.

All four are `abc.ABC`, matching every prior pluggable-strategy interface
in this codebase (`InputReader`/`ProjectImporter` in the reader layer,
`AddressAllocator`/`CloneValidator`/`ConflictDetector`/`CloneEngine` in
Step 5). This isn't cosmetic consistency — it's what makes the two
implementation strategies in §17 swappable behind the same `EtsWriter`
contract.

## 4. Serialization pipeline

Turns a `ProjectChangeSet` into ETS-shaped data, without touching any file:

1. **Diff.** `ProjectDiffer.diff(original, updated)` compares the two
   `ProjectModel`s field-by-field per object (by `id`) and produces the
   minimal `ProjectChangeSet` — one `ObjectChange` per object that actually
   differs, each carrying only the fields that changed. An object present
   in both with no field differences produces no `ObjectChange` at all:
   this is the mechanism that satisfies "preserve everything not
   intentionally modified" as a consequence of the diff, not a rule every
   caller must remember to follow.
2. **Identity.** For every `ObjectChange` with `change_kind == CREATE`,
   `IdentityStrategy.mint_id()` assigns a new object id (§6). `UPDATE`/
   `DELETE` changes always reuse the id the Reader originally captured —
   never re-minted, since reuse *is* what makes an edit an edit instead of
   a delete-and-recreate in ETS's eyes.
3. **Serialize.** `EtsSerializer.serialize()` turns the (now fully
   id-assigned) `ProjectChangeSet` into a `SerializedProject` — XML
   fragments plus the metadata needed to locate where each one goes in the
   base project's `project.xml`/`0.xml`. Topology (§10), parameters (§12)
   and manufacturer references (§13) each have their own handling inside
   this stage, described in their own sections below rather than as
   separate top-level interfaces — they're all the same "serialize one
   object kind correctly" concern, not independent pipelines.

## 5. Update pipeline

Applies a `SerializedProject` onto a real base `.knxproj`, producing a new
`.knxproj`:

1. Open the base archive; extract the inner project sub-archive
   (decrypting with whatever password-handling the eventual Reader for raw
   `.knxproj` establishes — not yet built, see Step 1's outcome).
2. Parse `project.xml`/`0.xml` into an editable XML tree.
3. For each serialized fragment: locate the target element by id (UPDATE/
   DELETE) or insert it in the appropriate parent (CREATE); apply only the
   changed attributes/children. Everything else in the tree is untouched
   by construction — the walk only ever visits elements a change actually
   names.
4. Re-serialize the tree to bytes.
5. Re-package the ZIP: replace only `project.xml`/`0.xml` inside the
   project sub-archive; copy every other archive entry (manufacturer
   folders, baggages, `knx_master.xml`, `.info`/`.certificate` where still
   valid — see §18 on signatures) byte-for-byte from the base archive.
6. Write the result to the output path.
7. **Recommended, not required by this design:** re-read the output with
   our own `JsonLdImporter`-equivalent-for-raw-`.knxproj` (once that
   exists) and assert every changed field matches the intended target and
   every untouched field matches the original — a concrete, automatable
   round-trip check rather than a hope. See §16.

## 6. Object identity strategy

`IdentityStrategy` mints ids only for `CREATE` changes. It is deliberately
a *different* concept from Clone Engine's `AddressAllocator` (Step 5):
`AddressAllocator` computes **bus addresses** (individual addresses, group
addresses — the numbers KNX telegrams actually carry); `IdentityStrategy`
computes **internal object ids** (the `Id` attribute ETS uses to identify
*which XML element is which*, independent of its address). Cloning a villa
needs both, together — a cloned device needs a new internal id *and* a new
individual address; they are minted by two different, independently
pluggable strategies, not conflated into one.

When a `ProjectChangeSet` originates from a Clone Engine `CloneMapping`
(Step 5), the convention is: build the changeset's ids directly from
`DeviceMapping.target_device_id` / `GroupAddressMapping.target_group_address_id`
rather than calling `IdentityStrategy` independently — Clone Engine already
computed a consistent mapping; `IdentityStrategy` exists for changes that
don't originate from a clone (e.g. "add a single new device").

## 7. Project GUID strategy

The `.info` sidecar for the reference project already showed us the shape:
`{"ProjectGuid": "31f9b2d9-7433-48d6-b127-1fea6c0c66b4", ...}`, a standard
UUID4.

- **Editing the reference project (or anything already cloned into it):**
  the `ProjectGuid` never changes — the Writer is patching the *same*
  project, not creating a new one.
- **"Generate new ETS projects"** (§17's last bullet): only meaningful as
  "assemble a new project from villas/devices we already have real data
  for" (an extreme case of cloning into a fresh base template), never as
  synthesizing a project with novel manufacturer data. A genuinely new
  project mints a fresh UUID4 for `ProjectGuid` and a fresh short
  installation-folder code following the observed `P-XXXX` pattern (exact
  derivation of that 4-hex-digit code is unconfirmed — see §18).

## 8. Device GUID strategy

Same shape as §6's `IdentityStrategy.mint_id("device", ...)`, plus one
device-specific fact: a `DeviceInstance` in `project.xml` is understood to
reference a specific product/application-program from a manufacturer
catalog (see §13) via a separate id — minting a device id says nothing
about *which product* the device is; that reference is copied verbatim
from the source device being cloned (§9), never invented.

## 9. Communication Object strategy

The important realization here: **communication objects are not
independently authored by this platform.** A device's communication
objects are defined by its application program (manufacturer XML) — fixed,
numbered, typed by the product itself. What our Writer actually controls
is which *group addresses* get connected to which of a device's
(pre-existing, product-defined) communication objects — i.e. the `Connectors`/
`Send`/`Receive` links, not the communication objects themselves.

Consequence for cloning: a cloned device reuses the *exact same* product
reference as its source (§8), which means it automatically has the exact
same set of communication objects, with the exact same DPTs and flags —
only their group-address connections change, to the newly-allocated cloned
group addresses. This is why Step 5 deliberately has no `CommunicationObjectMapping`
type of its own: `DeviceMapping` + `GroupAddressMapping` together already
fully determine it.

## 10. Group Address strategy

The Writer's job here is narrower than it sounds: **allocation** (which
number a new group address gets) is Clone Engine's `AddressAllocator`
(Step 5); the Writer's job is **serialization** — given a target address
(already decided) and the rest of a `GroupAddress`'s fields (name,
description, DPT reference, security mode), emit the correct `project.xml`
element/attributes for it, and (§9) wire its connections. `datapoint_type`
on our `GroupAddress` model is currently the Semantic Export's short DPT
name (e.g. `"switch"`) rather than a `knx_master.xml` DPT id (e.g.
`DPST-1-1`) — the Serializer needs a lookup table between the two, which
does not yet exist anywhere in this codebase (another concrete, scoped gap
for implementation, not a guess made now).

## 11. Topology serialization

A real gap in what `ProjectModel` currently carries, worth stating plainly:
Step 2 already noted bus topology (Area/Line) is *derivable* from a
device's `individual_address` string ("1.1.5") but is **not** modeled as
explicit `Area`/`Line` objects — `project.xml` almost certainly has an
actual nested `<Area><Line><DeviceInstance/></Line></Area>` structure (this
is standard, well-documented ETS topology shape, not itself in doubt the
way the file's exact attribute names are). The Serializer therefore has to
*derive* area/line grouping from `individual_address` at write time (group
devices by the first two dot-separated segments, emit/locate the matching
`Area`/`Line` elements, insert the `DeviceInstance` under the right one).
This derivation living only in the Writer, duplicating logic the Reader
doesn't have, is a known asymmetry — a future Reader enhancement to make
`Area`/`Line` first-class `ProjectModel` objects would remove it, but is
out of scope for this step.

## 12. Parameter serialization

Direct consequence of Step 2's finding: the Semantic Export carries **no**
ETS parameter values, so `Device.parameters` is always empty for every
project our current Reader can produce. **The Writer must never attempt to
serialize an empty `parameters` dict as "no parameters configured"** — that
would delete real configuration it simply never saw. The rule: if
`Device.parameters` is empty, the device's parameter block in `project.xml`
is left completely untouched (not even visited); only once a real value is
present (from a future `.knxproj`-native reader, or a future "edit
parameters" AI operation working from already-captured values) does the
Serializer touch that specific parameter's XML location, one value at a
time — never the whole block.

## 13. Manufacturer data handling

Never written, never regenerated — copied byte-for-byte in the Update
Pipeline's step 5 (§5). The only manufacturer-data *reference* the Writer
ever produces is pointing a cloned device at the *same* product id its
source device already used (§8, §9). Introducing a genuinely new product
type is out of scope for any operation this architecture supports (see
§17's "add device" row) — we have no legitimate way to author manufacturer
catalog data ourselves.

## 14. Validation rules

Two layers, deliberately not duplicated between them:

- **Reused from Clone Engine (Step 5):** address collisions (individual,
  group, villa-identity, internal) are exactly `ConflictDetector`'s job
  already — the Writer calls it rather than re-implementing address
  conflict logic. `ValidationSeverity`/`ValidationIssue`/`ValidationResult`
  from `clone_engine.models` are reused as-is here too (see §15 note on
  `WriteResult`).
- **Writer-specific, checked in the Serialization pipeline before any file
  is touched:**
  - Every `CREATE`d device's product reference resolves to a product
    already present in the base project's manufacturer folders (§13) — no
    dangling references.
  - Every `GroupAddress.datapoint_type` resolves via the DPT lookup table
    (§10) to a DPT id present in `knx_master.xml`.
  - Every minted id (§6) is unique within the target project — not just
    "different from the source id" but checked against the full target
    id-space, including other CREATEs in the same changeset.
  - `ObjectChange.object_id` for every `UPDATE`/`DELETE` actually exists in
    `original` (a change referencing an id the base project doesn't have
    is a diffing bug, not a valid instruction).

## 15. Compatibility with different ETS versions

`ProjectModel.tool_version` already captures the source project's ETS
version (Step 2, e.g. `"ETS 6.4.1 (Build 8718)"` — noting the real value
has known mojibake past the version number, see Step 2's test). The one
concrete, confirmed version-dependent fact from Step 1's research: room
type references changed meaning around ETS 6.3.8272.0. The design
consequence: `EtsSerializer` is version-aware via a small, pluggable
`EtsVersionProfile` concept (not built this step) selected from
`ProjectModel.tool_version`, so the Writer emits XML consistent with
*whatever version created the base project* rather than assuming the
latest schema. Concrete version-difference rules beyond the one already
confirmed are an open item (§18) pending real schema access.

## 16. Lossless round-trip requirements

**Only claimed at the `ProjectModel` boundary, and only for fields
`ProjectModel` actually captures.** This needs to be said explicitly
because the mission statement's "DigitalTwin / ProjectModel -> ETS Writer"
phrasing could be read as treating both as equally safe round-trip
sources. They are not:

- `ProjectModel` round-trip (`ETS -> Reader -> ProjectModel -> Writer ->
  ETS`, no DigitalTwin involved) is the one this architecture is built to
  make lossless, via the patch-not-regenerate principle (§1): anything
  `ProjectModel` doesn't carry (parameters, manufacturer data, anything
  outside our Reader's scope) is passed through untouched rather than
  dropped or regenerated wrong.
- `DigitalTwin` round-trip is **not** lossless by construction, and
  shouldn't be presented as such. Step 3's Entity/Capability grouping is a
  best-effort heuristic (documented there, with a real, accepted example
  of two capabilities that *don't* merge because their source names don't
  share wording) — going DigitalTwin -> ProjectModel would have to
  *regenerate* group address names/descriptions rather than recover the
  originals byte-for-byte. A DigitalTwin-originated edit (e.g. a clone)
  therefore always lands as new `CREATE` changes with regenerated naming,
  never as a claimed exact restoration of unseen original text.

**Verification, not just intention:** §5 step 7 proposes an actual
round-trip test harness (write with zero intended changes, re-read, assert
equality against the original) as the concrete way this requirement gets
checked once implementation exists, rather than resting on this document's
say-so.

## 17. Supporting future AI operations

| Operation | How it fits the pipeline |
|---|---|
| Rename rooms | Single-field `UPDATE` on a `Room`'s name; no identity/address work at all. |
| Clone villas | `CloneEngine.clone()` (Step 5) produces a `CloneMapping`; converted to `CREATE` changes for every device/group-address/room/scene, ids taken directly from the mapping (§6). |
| Renumber addresses | `UPDATE` changes with only `address`/`individual_address` fields set — same ids as the source, no CREATE at all. This is the "clone" case's simpler sibling: same shape, no identity minting needed. |
| Add/remove devices | Add: only valid when reusing a product already present in the base project (§13) — no novel manufacturer data. Remove: `DELETE` on the `DeviceInstance` and its own communication-object connections only; group addresses that lose their last connection are *not* auto-deleted (that's a separate, explicit operation) - consistent with §1. |
| Create scenes | `CREATE` changes referencing already-existing group addresses; exact scene XML shape is an open item (§18) - KNX scenes may be modeled as dedicated scene-extension communication objects rather than a simple standalone element, which needs schema confirmation before implementation. |
| Edit parameters | Only for parameters already captured (§12) - one `UPDATE` per parameter value, never a whole-block rewrite. |
| Generate new ETS projects | §7's "assemble from known-good parts" case - the Update Pipeline runs against a fresh/near-empty base template rather than the reference project, everything else identical. |

Every row reduces to the same `ProjectChangeSet` shape flowing through the
same pipeline — this table is really showing that seven different
product-level features are all one architecture, not seven.

## 18. Open risks — require real schema/data before implementation

Stated once here rather than scattered, so a reviewer can see the whole
risk surface in one place:

1. **We have never parsed a real `project.xml`.** Every structural
   assumption above (element names, `Id` format, nesting) is inferred from
   the Semantic Export's shape and general KNX/ETS knowledge, not verified
   against the actual internal format.
2. Whether Semantic Export node ids (`"prj:GA-266"`) actually equal the
   internal `project.xml` `Id` values, or merely resemble them, is
   unconfirmed.
3. Whether the project sub-archive's cryptographic signature/certificate
   survives a hand-patched `project.xml`, or whether the Writer needs to
   re-sign (and with what key/authority), is unknown.
4. The `datapoint_type` short-name -> `knx_master.xml` DPT-id mapping
   (§10) doesn't exist in this codebase yet.
5. Version-dependent schema differences beyond the one confirmed fact
   (§15) are unresearched.
6. Exact KNX scene XML shape (§17) is unconfirmed.

**Recommended path to close these:** either (a) obtain a real, unencrypted
sample `project.xml` (or the actual project password) to inspect directly,
or acquire the official KNX XML Project Schema via KNX Association
GitLab/Manufacturer Tool access; or (b) pursue the alternative
implementation strategy in §19 below, which sidesteps all six risks by
construction.

## 19. Two implementation strategies the interfaces support

Both fit behind the exact same `EtsWriter` interface (§3) - the risks in
§18 are what should decide which one gets built first, not this document.

- **A. Direct XML patching** (what §4/§5 describe in most detail): we parse
  and rewrite `project.xml` ourselves. Full control, but carries every risk
  in §18.
- **B. ETS App SDK.** Step 1's research surfaced the official "ETS Apps"
  SDK (C#/.NET, "guaranteed software access to ETS resources") for
  building tools that run *inside* ETS. A Writer built this way asks ETS
  itself to make the edit, which is inherently correct for whatever ETS
  version is running and sidesteps §18 entirely - at the cost of requiring
  a running ETS instance and a different tech stack (C#, not Python) for
  that piece. Worth a real prototype before committing to (A) at scale.

Both are legitimate `EtsWriter` implementations under the same interface;
this design does not pick one over the other.
