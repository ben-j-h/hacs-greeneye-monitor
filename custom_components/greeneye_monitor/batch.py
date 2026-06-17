"""Batched HA state writes for GreenEye Monitor entities."""

from collections.abc import Callable
from datetime import datetime

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_call_later

_DEBOUNCE_SECS = 0.05


class GreenEyeStateBatcher:
    """Coalesces async_write_ha_state calls across all entities from one GEM.

    When a UDP packet arrives from the GreenEye Monitor every 4-10 seconds,
    the greeneye library calls notify_all_listeners() on every channel, pulse
    counter, temperature sensor, and voltage sensor simultaneously. Without
    batching, each entity listener fires its own async_write_ha_state() call
    as a separate asyncio callback — up to ~109 callbacks for a fully-loaded
    32-channel GEM-P.

    This batcher collects every entity that gets notified into a dirty set,
    then flushes them all in a single loop pass 50ms after the last listener
    fires. The result is one asyncio wakeup instead of N, and all state
    changes reach HA in the same event-loop iteration.

    Because the flush window (50ms) is far shorter than the GEM's packet
    interval (4-10s), there is no artificial throttling of update frequency.
    Entities update at the native GEM rate rather than the old 30s/5min
    per-entity Throttle values.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._dirty: set[Entity] = set()
        self._cancel: Callable[[], None] | None = None

    def mark_dirty(self, entity: Entity) -> None:
        """Mark an entity dirty and (re)start the flush timer."""
        self._dirty.add(entity)
        if self._cancel:
            self._cancel()
        self._cancel = async_call_later(self._hass, _DEBOUNCE_SECS, self._flush)

    def remove(self, entity: Entity) -> None:
        """Drop a departing entity so the flush doesn't write stale state."""
        self._dirty.discard(entity)

    @callback
    def _flush(self, _now: datetime) -> None:
        self._cancel = None
        dirty, self._dirty = self._dirty, set()
        for entity in dirty:
            entity.async_write_ha_state()

    def cancel(self) -> None:
        """Cancel any pending flush — called on integration unload."""
        if self._cancel:
            self._cancel()
            self._cancel = None
        self._dirty.clear()
