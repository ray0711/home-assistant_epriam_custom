import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
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
    async_add_entities([
        EPriamContinuousBatterySensor(manager),
        EPriamTimeRemainingSensor(manager)
    ])

class EPriamContinuousBatterySensor(SensorEntity):
    def __init__(self, manager: EPriamManager):
        self.manager = manager
        self._attr_name = "E-Priam Battery"
        self._attr_unique_id = "epriam_continuous_battery_sensor"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_native_unit_of_measurement = "%"

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
    def native_value(self):
        return self.manager.battery_level


class EPriamTimeRemainingSensor(SensorEntity):
    def __init__(self, manager: EPriamManager):
        self.manager = manager
        self._attr_name = "Rocking Time Remaining"
        self._attr_unique_id = "epriam_continuous_time_remaining"
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_native_unit_of_measurement = "s"
        self._attr_icon = "mdi:timer-sand"

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
        return True 

    @property
    def native_value(self):
        return self.manager.time_remaining
