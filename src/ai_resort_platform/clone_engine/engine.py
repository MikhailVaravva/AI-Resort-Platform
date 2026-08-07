"""Clone Engine interfaces.

Design only - no method here has a real implementation (see the project
goal: Reference Villa -> Digital Twin -> Clone Engine -> Deployment; this
file is the Clone Engine's contract, Step 6+ fills it in).

## Pipeline

CloneEngine.clone() is the single entry point. A real implementation is
expected to run these stages in order, each delegated to its own pluggable
interface below:

1. **Validate the profile** (CloneValidator.validate_profile) - is the
   request well-formed (non-empty target name/code, no obvious identity
   collision with an existing villa)? Fails fast before any address work.
2. **Allocate addresses** (AddressAllocator) - for every source device's
   individual address and every source group address, compute a target
   address. Pluggable because the allocation policy is a resort-level
   decision, not a Clone Engine one - e.g. the reference villa "Villa A1"
   already uses individual addresses on Area 1 / Line 1 and group addresses
   under main group 1 / middle group 1, so an allocator might increment
   line or middle-group per villa; a resort with a different convention
   swaps in a different AddressAllocator, not a different CloneEngine.
3. **Build the mapping** - assemble DeviceMapping, GroupAddressMapping,
   RoomMapping and SceneMapping records from the allocated addresses, then
   the aggregate CloneMapping. Entities are deliberately NOT mapped here:
   they're a derived concept (see digital_twin/builder.py's grouping
   heuristic), so the cloned Villa's entities are re-derived by re-running
   that same builder over the cloned group addresses, not by copying or
   remapping the source Entities directly.
4. **Detect conflicts** (ConflictDetector.detect_conflicts) - check the
   fully-built CloneMapping's target addresses against every address
   already in use across the whole Resort (every existing villa, including
   the reference villa itself - it stays on the bus after being cloned).
5. **Materialize the clone** - apply the mapping to produce the new Villa.
   This is the one stage with no interface below: it is exactly "cloning"
   in the sense this step is explicitly scoped to not implement.

CloneResult.villa is None whenever CloneResult.validation.is_valid is
False - a failed clone attempt never returns a partially-built Villa.
"""

import abc

from ai_resort_platform.clone_engine.models import (
    CloneMapping,
    CloneProfile,
    CloneResult,
    ValidationResult,
)
from ai_resort_platform.digital_twin.models import Resort


class AddressAllocator(abc.ABC):
    """Computes target addresses for a clone. Stage 2 of the pipeline."""

    @abc.abstractmethod
    def allocate_individual_address(self, source_address: str, profile: CloneProfile) -> str:
        """Return the target individual address for one cloned device."""
        raise NotImplementedError

    @abc.abstractmethod
    def allocate_group_address(self, source_address: str, profile: CloneProfile) -> str:
        """Return the target group address for one cloned group address."""
        raise NotImplementedError


class CloneValidator(abc.ABC):
    """Validates a CloneProfile before any address work happens. Stage 1."""

    @abc.abstractmethod
    def validate_profile(self, profile: CloneProfile, resort: Resort) -> ValidationResult:
        """Check the profile itself: non-empty target identity, and that
        `target_villa_name`/`target_villa_code` don't already identify a
        villa in `resort`. Does not look at addresses - that's
        ConflictDetector's job, after allocation has actually happened.
        """
        raise NotImplementedError


class ConflictDetector(abc.ABC):
    """Checks a built CloneMapping's addresses against the resort. Stage 4.

    Every issue this raises should carry a `ConflictKind` (see models.py)
    in its context, identifying which of the four collision kinds fired:
    individual-address, group-address, villa-identity, or an internal
    collision between two targets within the same CloneMapping (which
    would indicate a bug in the AddressAllocator, not a resort conflict).
    """

    @abc.abstractmethod
    def detect_conflicts(self, resort: Resort, mapping: CloneMapping) -> ValidationResult:
        raise NotImplementedError


class CloneEngine(abc.ABC):
    """Produces a new Villa from a reference Villa and a CloneProfile.

    See the module docstring for the five-stage pipeline this orchestrates.
    """

    @abc.abstractmethod
    def clone(self, resort: Resort, profile: CloneProfile) -> CloneResult:
        """Clone `profile.source_villa_id` (must be a villa in `resort`)
        into a new Villa per `profile`. Returns a CloneResult whose
        `validation` reports every issue found at any stage; `villa` and
        `mapping` are populated only if `validation.is_valid`.
        """
        raise NotImplementedError
