import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_INFO
from .manager import EPriamManager

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager: EPriamManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EPriamDriveModeSelect(manager)])

class EPriamDriveModeSelect(SelectEntity):
    def __init__(self, manager: EPriamManager):
        self.manager = manager
        self._attr_name = "E-Priam Drive Mode"
        self._attr_unique_id = "epriam_custom_drive_mode"
        self._attr_options = ["Eco", "Tour", "Boost"]
        self._attr_icon = "mdi:speedometer"

    @property
    def device_info(self):
        return DEVICE_INFO

    async def async_added_to_hass(self):
        self.manager.register_callback(self.async_write_ha_state)

    @property
    def available(self):
        return self.manager.is_connected

    @property
    def current_option(self):
        return self.manager.drive_mode

    async def async_select_option(self, option: str) -> None:
        await self.manager.set_drive_mode(option)
