import logging
from homeassistant.components.number import NumberEntity, NumberMode
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
    async_add_entities([
        EPriamIntensityNumber(manager),
        EPriamDurationNumber(manager)
    ])

class EPriamIntensityNumber(NumberEntity):
    def __init__(self, manager: EPriamManager):
        self.manager = manager
        self._attr_name = "Rocking Intensity"
        self._attr_unique_id = "epriam_custom_rocking_intensity"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 3
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        self._attr_icon = "mdi:vibrate"

    @property
    def device_info(self):
        return DEVICE_INFO

    async def async_added_to_hass(self):
        self.manager.register_callback(self.async_write_ha_state)

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        return self.manager.rocking_intensity

    async def async_set_native_value(self, value: float) -> None:
        self.manager.rocking_intensity = int(value)
        self.manager._notify_callbacks()

class EPriamDurationNumber(NumberEntity):
    def __init__(self, manager: EPriamManager):
        self.manager = manager
        self._attr_name = "Rocking Duration"
        self._attr_unique_id = "epriam_custom_rocking_duration"
        self._attr_native_min_value = 1
        self._attr_native_max_value = 180
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "min"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:timer-outline"

    @property
    def device_info(self):
        return DEVICE_INFO

    async def async_added_to_hass(self):
        self.manager.register_callback(self.async_write_ha_state)

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        return self.manager.rocking_duration

    async def async_set_native_value(self, value: float) -> None:
        self.manager.rocking_duration = int(value)
        self.manager._notify_callbacks()
