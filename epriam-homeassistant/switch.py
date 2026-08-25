import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .manager import EPriamManager

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager: EPriamManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EPriamContinuousSwitch(manager)])

class EPriamContinuousSwitch(SwitchEntity):
    def __init__(self, manager: EPriamManager):
        self.manager = manager
        self._attr_name = "E-Priam Rocking"
        self._attr_unique_id = "epriam_continuous_rocking_switch"
        self._attr_icon = "mdi:baby-carriage"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, "cybex_epriam")},
            "name": "Cybex e-Priam",
            "manufacturer": "Cybex",
            "model": "e-Priam Stroller",
        }

    async def async_added_to_hass(self):
        self.manager.register_callback(self.async_write_ha_state)

    @property
    def available(self):
        return self.manager.is_connected

    @property
    def is_on(self):
        return self.manager.rocking_active

    async def async_turn_on(self, **kwargs):
        await self.manager.set_rocking_state(True)

    async def async_turn_off(self, **kwargs):
        await self.manager.set_rocking_state(False)
