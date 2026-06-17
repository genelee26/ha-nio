"""Binary sensors for the NIO integration.

Door/window are aggregate checks across all openings — fixes the silently
broken YAML templates that referenced non-existent ``door_front_left_status``
fields (live API returns ``door_ajar_front_left_status``).

Field semantics (field-tested 2026-06-06 — all 5 openings cycled one by one,
12-step sequence matched 1:1 against raw API captures):
- ``*_ajar_status``: 1 = closed, 0 = open
- ``vehicle_lock_status``: 1 = locked, 0 = unlocked
- ``win_*_posn``: 0 = closed, >0 = open position (carried over from the
  legacy YAML templates; field names unchanged)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOOR_AJAR_FIELDS, DOOR_CLOSED, LOCK_LOCKED, WINDOW_POSN_FIELDS
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator
from .entity import NioEntity


def _any_door_open(data: dict[str, Any]) -> bool | None:
    doors = data.get("door_status") or {}
    values = [doors.get(f) for f in DOOR_AJAR_FIELDS]
    if all(v is None for v in values):
        return None
    # 0 = open (field-tested); anything that isn't "closed" counts as open.
    return any(v is not None and v != DOOR_CLOSED for v in values)


def _any_window_open(data: dict[str, Any]) -> bool | None:
    windows = data.get("window_status") or {}
    values = [windows.get(f) for f in WINDOW_POSN_FIELDS]
    if all(v is None for v in values):
        return None
    return any(v not in (None, 0) for v in values)


def _is_driving(data: dict[str, Any]) -> bool | None:
    state = (data.get("exterior_status") or {}).get("vehicle_state")
    return None if state is None else state == 1


def _is_sleeping(data: dict[str, Any]) -> bool | None:
    exterior = data.get("exterior_status") or {}
    state = exterior.get("vehicle_state")
    if state is None:
        return None
    return state != 1 and exterior.get("comf_ena", 0) != 1


def _is_unlocked(data: dict[str, Any]) -> bool | None:
    lock = (data.get("door_status") or {}).get("vehicle_lock_status")
    # device_class LOCK: on = unlocked
    return None if lock is None else lock != LOCK_LOCKED


def _is_charging(data: dict[str, Any]) -> bool | None:
    state = (data.get("soc_status") or {}).get("charge_state")
    return None if state is None else state != 0


def _is_connected(data: dict[str, Any]) -> bool | None:
    return (data.get("connection_status") or {}).get("connected")


@dataclass(frozen=True, kw_only=True)
class NioBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[NioBinarySensorDescription, ...] = (
    NioBinarySensorDescription(
        key="driving",
        translation_key="driving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=_is_driving,
    ),
    NioBinarySensorDescription(
        key="sleeping",
        translation_key="sleeping",
        icon="mdi:sleep",
        value_fn=_is_sleeping,
    ),
    NioBinarySensorDescription(
        key="door",
        translation_key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_any_door_open,
    ),
    NioBinarySensorDescription(
        key="window",
        translation_key="window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_any_window_open,
    ),
    NioBinarySensorDescription(
        key="lock",
        translation_key="lock",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_is_unlocked,
    ),
    NioBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=_is_charging,
    ),
    NioBinarySensorDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_is_connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.status
    async_add_entities(
        NioBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class NioBinarySensor(NioEntity, BinarySensorEntity):
    """A coordinator-backed NIO binary sensor."""

    entity_description: NioBinarySensorDescription

    def __init__(
        self,
        coordinator: NioDataUpdateCoordinator,
        description: NioBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
