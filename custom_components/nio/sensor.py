"""Sensors for the NIO integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import NioConfigEntry, NioDataUpdateCoordinator
from .entity import NioEntity


def _section(data: dict[str, Any], section: str, key: str) -> Any:
    value = (data.get(section) or {}).get(key)
    return value


def _achievement_rate(data: dict[str, Any]) -> float | None:
    soc = data.get("soc_status") or {}
    cltc = soc.get("remaining_range")
    actual = soc.get("remaining_actual_range")
    if not cltc or actual is None:
        return None
    return round(actual / cltc * 100, 1)


@dataclass(frozen=True, kw_only=True)
class NioSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSORS: tuple[NioSensorDescription, ...] = (
    # --- parity with the old YAML setup ---
    NioSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: _section(d, "soc_status", "soc"),
    ),
    NioSensorDescription(
        key="remaining_range",
        translation_key="remaining_range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: _section(d, "soc_status", "remaining_range"),
    ),
    NioSensorDescription(
        key="remaining_actual_range",
        translation_key="remaining_actual_range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: _section(d, "soc_status", "remaining_actual_range"),
    ),
    NioSensorDescription(
        key="range_achievement_rate",
        translation_key="range_achievement_rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:percent-circle",
        value_fn=_achievement_rate,
    ),
    NioSensorDescription(
        key="vehicle_state",
        translation_key="vehicle_state",
        device_class=SensorDeviceClass.ENUM,
        options=["driving", "parked", "resting", "unknown"],
        value_fn=lambda d: {1: "driving", 2: "parked", 3: "resting"}.get(
            _section(d, "exterior_status", "vehicle_state"), "unknown"
        ),
    ),
    # --- extended: energy / charging ---
    NioSensorDescription(
        key="charging_power",
        translation_key="charging_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        value_fn=lambda d: _section(d, "soc_status", "charging_power"),
    ),
    # --- extended: climate ---
    NioSensorDescription(
        key="inside_temperature",
        translation_key="inside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _section(d, "hvac_status", "temperature"),
    ),
    NioSensorDescription(
        key="outside_temperature",
        translation_key="outside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _section(d, "hvac_status", "outside_temperature"),
    ),
    # --- extended: odometer ---
    NioSensorDescription(
        key="mileage",
        translation_key="mileage",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:counter",
        value_fn=lambda d: _section(d, "exterior_status", "mileage"),
    ),
    # --- extended: tyres (diagnostic) ---
    *(
        NioSensorDescription(
            key=f"tyre_pressure_{corner}",
            translation_key=f"tyre_pressure_{corner}",
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPressure.BAR,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:car-tire-alert",
            value_fn=(
                lambda field: lambda d: _section(d, "tyre_status", field)
            )(f"{corner}_wheel_press_bar"),
        )
        for corner in ("front_left", "front_right", "rear_left", "rear_right")
    ),
    # --- extended: firmware (diagnostic) ---
    NioSensorDescription(
        key="fota_version",
        translation_key="fota_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:cellphone-arrow-down",
        value_fn=lambda d: _section(d, "fota_status", "current_version"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        NioSensor(coordinator, description) for description in SENSORS
    )


class NioSensor(NioEntity, SensorEntity):
    """A coordinator-backed NIO sensor."""

    entity_description: NioSensorDescription

    def __init__(
        self,
        coordinator: NioDataUpdateCoordinator,
        description: NioSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)
