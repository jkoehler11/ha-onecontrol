"""Number platform for OneControl BLE integration.

Creates number entities for device configuration values accessed
via IDS-CAN PID_READ_WRITE (0x11) requests.

Initial target: generator auto-start and quiet-hours configuration.
Future: leveler sensitivity, HVAC offsets, etc.

Reference: IDS-CAN REQUEST frame definitions (ids_can_wire.py)
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    GEN_PID_AUTO_START_LOW_VOLTAGE,
    GEN_PID_AUTO_START_LOW_VOLTAGE_ENABLED,
    GEN_PID_AUTO_START_HI_TEMP_C,
    GEN_PID_QUIET_HOURS_ENABLED,
    GEN_PID_QUIET_HOURS_START_TIME,
    GEN_PID_QUIET_HOURS_END_TIME,
    GEN_PID_AUTO_RUN_DURATION_MINUTES,
    GEN_PID_AUTO_RUN_MIN_OFF_TIME_MINUTES,
    GEN_PID_LABELS,
    GEN_PID_UNITS,
)
from .coordinator import OneControlCoordinator
from .protocol.events import GeneratorStatus

_LOGGER = logging.getLogger(__name__)

# Generator PID definitions: (pid_key, min_val, max_val, step, default)
_GENERATOR_PID_CONFIG: tuple[tuple[str, float, float, float, float | None], ...] = (
    (GEN_PID_AUTO_START_LOW_VOLTAGE, 10.0, 15.0, 0.1, 12.0),
    (GEN_PID_AUTO_START_LOW_VOLTAGE_ENABLED, 0.0, 1.0, 1.0, 0.0),
    (GEN_PID_AUTO_START_HI_TEMP_C, 20.0, 50.0, 1.0, 35.0),
    (GEN_PID_QUIET_HOURS_ENABLED, 0.0, 1.0, 1.0, 0.0),
    (GEN_PID_QUIET_HOURS_START_TIME, 0.0, 1439.0, 15.0, 1320.0),  # 22:00
    (GEN_PID_QUIET_HOURS_END_TIME, 0.0, 1439.0, 15.0, 360.0),   # 06:00
    (GEN_PID_AUTO_RUN_DURATION_MINUTES, 15.0, 480.0, 15.0, 120.0),
    (GEN_PID_AUTO_RUN_MIN_OFF_TIME_MINUTES, 15.0, 480.0, 15.0, 60.0),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OneControl number entities from a config entry."""
    coordinator: OneControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]

    # Generator config numbers are created dynamically when a generator is discovered
    discovered_generators: set[str] = set()

    @callback
    def _on_event(event: Any) -> None:
        if isinstance(event, GeneratorStatus):
            key = f"{event.table_id:02x}:{event.device_id:02x}"
            if key not in discovered_generators:
                discovered_generators.add(key)
                entities = [
                    OneControlGeneratorConfigNumber(
                        coordinator, address,
                        event.table_id, event.device_id,
                        pid_key, pid_min, pid_max, pid_step, pid_default,
                    )
                    for pid_key, pid_min, pid_max, pid_step, pid_default
                    in _GENERATOR_PID_CONFIG
                ]
                async_add_entities(entities)

    coordinator.register_event_callback(_on_event)

    # Create for already-discovered generators
    for key in coordinator.generators:
        if key not in discovered_generators:
            discovered_generators.add(key)
            gen = coordinator.generators[key]
            entities = [
                OneControlGeneratorConfigNumber(
                    coordinator, address,
                    gen.table_id, gen.device_id,
                    pid_key, pid_min, pid_max, pid_step, pid_default,
                )
                for pid_key, pid_min, pid_max, pid_step, pid_default
                in _GENERATOR_PID_CONFIG
            ]
            async_add_entities(entities)


class OneControlGeneratorConfigNumber(
    CoordinatorEntity[OneControlCoordinator], NumberEntity
):
    """Number entity for a generator configuration PID.

    Reads/writes the PID value via IDS-CAN PID_READ_WRITE requests.
    Falls back to cached/local values when the gateway is a legacy
    MyRvLink device that doesn't support IDS-CAN PID access.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: OneControlCoordinator,
        address: str,
        table_id: int,
        device_id: int,
        pid_key: str,
        pid_min: float,
        pid_max: float,
        pid_step: float,
        pid_default: float | None,
    ) -> None:
        super().__init__(coordinator)
        self._table_id = table_id
        self._device_id = device_id
        self._pid_key = pid_key
        self._attr_native_min_value = pid_min
        self._attr_native_max_value = pid_max
        self._attr_native_step = pid_step
        self._default = pid_default
        self._cached_value: float | None = pid_default

        mac = address.replace(":", "").lower()
        safe_pid = pid_key.lower().replace(" ", "_")[:40]
        self._attr_unique_id = f"{mac}_gen_{device_id:02x}_{safe_pid}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"OneControl {address}",
            manufacturer="Lippert / LCI",
            model="BLE Gateway",
            connections={("bluetooth", address)},
        )

        label = GEN_PID_LABELS.get(pid_key, pid_key)
        self._attr_name = f"Generator {label}"

        unit = GEN_PID_UNITS.get(pid_key)
        if unit:
            self._attr_native_unit_of_measurement = unit

        self._unsub = coordinator.register_event_callback(self._on_event)

    @property
    def available(self) -> bool:
        """Available when the gateway is connected and a generator exists."""
        key = f"{self._table_id:02x}:{self._device_id:02x}"
        return (
            self.coordinator.connected
            and key in self.coordinator.generators
        )

    @property
    def native_value(self) -> float | None:
        """Return the cached PID value."""
        return self._cached_value

    async def async_set_native_value(self, value: float) -> None:
        """Write a new value to the generator PID.

        Only supported on IDS-CAN BLE gateways that accept PID_READ_WRITE
        requests. MyRvLink gateways will log a warning and cache locally.
        """
        self._cached_value = value
        self.async_write_ha_state()

        if not self.coordinator.is_can_ble_gateway:
            _LOGGER.warning(
                "PID write not supported for MyRvLink gateway: %s=%s",
                self._pid_key, value,
            )
            return

        # Determine value encoding based on PID type
        # Boolean PIDs use single byte 0/1; others use BE16 fixed-point
        bool_pids = {
            GEN_PID_AUTO_START_LOW_VOLTAGE_ENABLED,
            GEN_PID_QUIET_HOURS_ENABLED,
        }
        if self._pid_key in bool_pids:
            raw = bytes([1 if value >= 1.0 else 0])
        elif self._pid_key in (GEN_PID_QUIET_HOURS_START_TIME, GEN_PID_QUIET_HOURS_END_TIME):
            # Time in minutes since midnight, BE16
            raw = bytes([(int(value) >> 8) & 0xFF, int(value) & 0xFF])
        elif self._pid_key == GEN_PID_AUTO_START_LOW_VOLTAGE:
            # 8.8 fixed-point volts (BE16)
            raw_val = int(value * 256) & 0xFFFF
            raw = bytes([(raw_val >> 8) & 0xFF, raw_val & 0xFF])
        elif self._pid_key == GEN_PID_AUTO_START_HI_TEMP_C:
            # 8.8 fixed-point Celsius (BE16)
            raw_val = int(value * 256) & 0xFFFF
            raw = bytes([(raw_val >> 8) & 0xFF, raw_val & 0xFF])
        else:
            # Generic BE16
            raw = bytes([(int(value) >> 8) & 0xFF, int(value) & 0xFF])

        try:
            await self.coordinator.async_write_pid(
                self._pid_key, self._table_id, self._device_id, value, raw
            )
            _LOGGER.debug("PID write sent: %s=%s", self._pid_key, value)
        except Exception as exc:
            _LOGGER.error("PID write failed %s: %s", self._pid_key, exc)

    @callback
    def _on_event(self, event: Any) -> None:
        """Handle incoming events — update cached value when generator state changes."""
        if (
            isinstance(event, GeneratorStatus)
            and event.table_id == self._table_id
            and event.device_id == self._device_id
        ):
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up event subscription."""
        self._unsub()
