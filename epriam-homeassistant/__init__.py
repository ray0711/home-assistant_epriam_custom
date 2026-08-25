import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN
from .manager import EPriamManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.NUMBER
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = EPriamManager(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = manager
    
    await manager.start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_send_payload(call):
        payload = call.data.get("payload")
        await manager.async_send_raw_payload(payload)

    hass.services.async_register(
        DOMAIN,
        "send_rocking_payload",
        handle_send_payload,
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager: EPriamManager = hass.data[DOMAIN][entry.entry_id]
    await manager.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "send_rocking_payload")
    return unload_ok
