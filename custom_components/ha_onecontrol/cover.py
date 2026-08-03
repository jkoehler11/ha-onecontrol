"""Cover platform for OneControl BLE integration.

Creates Cover entities that show the current state (opening/closing/stopped)
and allow control via open/close/stop commands.

Also creates companion button entities for advanced H-Bridge commands:
  - Auto Open / Auto Close (weather-sensing awning modes)
  - Clear Latch (reset motor fault latch)
  - Home Reset (recalibrate motor position)

Reference: INTERNALS.md § Cover / Slide / Awning
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)


def _is_valid_device_id(device_id: int) -> bool:
    """Check if device_id is valid (not a sentinel value like 0x0000)."""
    # Exclude invalid/placeholder device IDs
    invalid_ids = {0x00, 0x8F, 0x59}
    return device_id not in invalid_ids
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OneControlCoordinator
from .protocol.commands import CommandBuilder
from .protocol.events import CoverStatus

_LOGGER = logging.getLogger(__name__)

# ── Advanced H-Bridge button definitions ───────────────────────────────────

_HBRIDGE_BUTTONS: tuple[tuple[int, str, str, str], ...] = (
    # (command_byte, suffix, label, icon)
    (CommandBuilder.HBRIDGE_AUTO_OPEN_CMD, "auto_open", "Auto Open", "mdi:weather-sunny"),
    (CommandBuilder.HBRIDGE_AUTO_CLOSE_CMD, "auto_close", "Auto Close", "mdi:weather-night"),
    (CommandBuilder.HBRIDGE_CLEAR_LATCH_CMD, "clear_latch", "Clear Latch", "mdi:lock-reset"),
    (CommandBuilder.HBRIDGE_HOME_RESET_CMD, "home_reset", "Home Reset", "mdi:home-import-outline"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OneControl cover entities from a config entry."""
    coordinator: OneControlCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]

    discovered: set[str] = set()

    @callback
    def _on_event(event: Any) -> None:
        if isinstance(event, CoverStatus):
            if not _is_valid_device_id(event.device_id):
                return
            key = f"{event.table_id:02x}:{event.device_id:02x}"
            if key not in discovered:
                discovered.add(key)
                _add_cover_and_buttons(coordinator, address, event.table_id, event.device_id, async_add_entities)

    coordinator.register_event_callback(_on_event)

    for key, cov in coordinator.covers.items():
        if key not in discovered:
            discovered.add(key)
            _add_cover_and_buttons(coordinator, address, cov.table_id, cov.device_id, async_add_entities)


def _add_cover_and_buttons(
    coordinator: OneControlCoordinator,
    address: str,
    table_id: int,
    device_id: int,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the cover entity and its companion advanced-command buttons."""
    entities: list = [OneControlCover(coordinator, address, table_id, device_id)]

    mac = address.replace(":", "").lower()
    device_info = DeviceInfo(
        identifiers={(DOMAIN, address)},
        name=f"OneControl {address}",
        manufacturer="Lippert / LCI",
        model="BLE Gateway",
        connections={("bluetooth", address)},
    )

    for cmd_byte, suffix, label, icon in _HBRIDGE_BUTTONS:
        entities.append(
            OneControlCoverButton(
                coordinator=coordinator,
                device_info=device_info,
                unique_id=f"{mac}_cover_{table_id:02x}_{device_id:02x}_{suffix}",
                name=label,
                icon=icon,
                table_id=table_id,
                device_id=device_id,
                command_byte=cmd_byte,
            )
        )

    async_add_entities(entities)


class OneControlCover(CoordinatorEntity[OneControlCoordinator], CoverEntity):
    """Cover entity with open/close/stop control.

    Shows opening / closing / stopped state from the H-Bridge status event.
    Position is exposed when available (0xFF means unknown).
    """

    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.AWNING
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    @property
    def supported_features(self) -> int:
        """Return supported features for this cover entity."""
        _LOGGER.debug(
            "Cover supported_features for %s = %s",
            self._key,
            int(self._attr_supported_features),
        )
        return int(self._attr_supported_features)

    def __init__(
        self,
        coordinator: OneControlCoordinator,
        address: str,
        table_id: int,
        device_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._table_id = table_id
        self._device_id = device_id
        self._key = f"{table_id:02x}:{device_id:02x}"
        mac = address.replace(":", "").lower()
        self._attr_unique_id = f"{mac}_cover_{table_id:02x}_{device_id:02x}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"OneControl {address}",
            manufacturer="Lippert / LCI",
            model="BLE Gateway",
            connections={("bluetooth", address)},
        )
        self._unsub = coordinator.register_event_callback(self._on_event)

    @property
    def name(self) -> str:
        return self.coordinator.device_name(self._table_id, self._device_id)

    @property
    def available(self) -> bool:
        # Cover controls should remain available once the device has been
        # discovered, and while the gateway link is connected.
        available = self._key in self.coordinator.covers or self.coordinator.connected
        _LOGGER.debug("Cover available for %s = %s", self._key, available)
        return available

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is fully closed.

        Position 0 = fully retracted/closed.
        None returned when position is unknown (0xFF or absent).
        """
        cov = self.coordinator.covers.get(self._key)
        if not cov:
            return None
        # Motor is running — state is transitional
        if cov.ha_state in ("opening", "closing"):
            return False
        # Motor stopped — use position if available
        if cov.position is None or cov.position == 0xFF:
            return None
        return cov.position == 0

    @property
    def is_opening(self) -> bool:
        cov = self.coordinator.covers.get(self._key)
        return cov.ha_state == "opening" if cov else False

    @property
    def is_closing(self) -> bool:
        cov = self.coordinator.covers.get(self._key)
        return cov.ha_state == "closing" if cov else False

    @property
    def current_cover_position(self) -> int | None:
        """Position 0-100, None if unknown."""
        cov = self.coordinator.covers.get(self._key)
        if not cov or cov.position is None or cov.position == 0xFF:
            return None
        return cov.position

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cov = self.coordinator.covers.get(self._key)
        if not cov:
            return {}
        return {
            "raw_status": f"0x{cov.status:02X}",
            "table_id": self._table_id,
            "device_id": self._device_id,
        }

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (extend motor)."""
        _LOGGER.info("Cover open requested key=%s table=%d device=0x%02X", self._key, self._table_id, self._device_id)
        await self.coordinator.async_cover(self._table_id, self._device_id, 0x01)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (retract motor)."""
        _LOGGER.debug("Cover close key=%s table=%d device=0x%02X", self._key, self._table_id, self._device_id)
        await self.coordinator.async_cover(self._table_id, self._device_id, 0x02)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover motor."""
        _LOGGER.debug("Cover stop key=%s table=%d device=0x%02X", self._key, self._table_id, self._device_id)
        await self.coordinator.async_cover(self._table_id, self._device_id, 0x00)

    async def async_will_remove_from_hass(self) -> None:
        self._unsub()

    @callback
    def _on_event(self, event: Any) -> None:
        if (
            isinstance(event, CoverStatus)
            and event.table_id == self._table_id
            and event.device_id == self._device_id
        ):
            self.async_write_ha_state()


class OneControlCoverButton(CoordinatorEntity[OneControlCoordinator], ButtonEntity):
    """Button entity for an advanced H-Bridge cover command.

    Sends a single-fire command (no repeating) to the gateway for
    operations like Auto Open, Auto Close, Clear Latch, or Home Reset.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: OneControlCoordinator,
        device_info: DeviceInfo,
        unique_id: str,
        name: str,
        icon: str,
        table_id: int,
        device_id: int,
        command_byte: int,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = device_info
        self._table_id = table_id
        self._device_id = device_id
        self._command_byte = command_byte

    @property
    def available(self) -> bool:
        """Available when the gateway is connected."""
        return self.coordinator.connected

    async def async_press(self) -> None:
        """Send the advanced cover command to the gateway."""
        _LOGGER.info(
            "Cover button '%s' pressed table=%d device=0x%02X cmd=0x%02X",
            self._attr_name,
            self._table_id,
            self._device_id,
            self._command_byte,
        )
        await self.coordinator.async_cover_advanced(
            self._table_id, self._device_id, self._command_byte,
        )
