import logging
import asyncio
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.core import HomeAssistant

from .const import CHAR_STATUS, CHAR_ROCKING, CHAR_DRIVE_MODE, CYBEX_MANUFACTURER_ID

_LOGGER = logging.getLogger(__name__)

class EPriamManager:
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self.client = None
        self.battery_level = None
        self.is_connected = False
        
        self.drive_mode = "Tour"
        self.rocking_intensity = 3
        self.rocking_duration = 30
        
        self.rocking_active = False
        self.time_remaining = 0
        
        self._callbacks = []
        self._connect_task = None
        self._shutdown = False

    def register_callback(self, callback):
        self._callbacks.append(callback)
        callback()

    def _notify_callbacks(self):
        for cb in self._callbacks:
            try:
                cb()
            except Exception as e:
                pass

    def _get_device(self):
        for discovery_info in async_discovered_service_info(self.hass, connectable=True):
            if CYBEX_MANUFACTURER_ID in discovery_info.manufacturer_data:
                return discovery_info.device
            if "a1fc0101-78d3-40c2-9b6f-3c5f7b2797df" in discovery_info.service_uuids:
                return discovery_info.device
            if discovery_info.name and "Priam" in discovery_info.name:
                return discovery_info.device
        return None

    def _get_characteristic(self, uuid_str, required_property=None):
        if not self.client or not self.client.services:
            return None
        for service in self.client.services:
            for char in service.characteristics:
                if char.uuid.lower() == uuid_str.lower():
                    if required_property:
                        if any(required_property in p.lower() for p in char.properties):
                            return char
                    else:
                        return char
        return None

    def _notification_handler(self, sender, data: bytearray):
        _LOGGER.info(f"[Manager] Battery/Status Notify Payload: {data.hex()}")
        if len(data) >= 4:
            voltage = (data[3] & 0xFF) * 2
            pct = int(((voltage - 315) * 100) / 65)
            self.battery_level = max(0, min(100, pct))
        self._notify_callbacks()

    def _rocking_notification_handler(self, sender, data: bytearray):
        _LOGGER.info(f"[Manager] Rocking Notify Payload: {data.hex()}")
        if len(data) >= 5:
            intensity = data[0] & 0xF
            
            # 16-bit integer (little endian) in seconds
            time_left = (data[1] & 255) | ((data[2] & 255) << 8)
            
            self.time_remaining = time_left
            self.rocking_active = (time_left > 0 or intensity > 0)
            
            if 1 <= intensity <= 3:
                self.rocking_intensity = intensity
            
            if data[0] == 0x94: # 148 ^ 128 = 20 (Brake not engaged)
                _LOGGER.warning("[Manager] Stroller reported: Brake not engaged. Rocking cannot start.")
                self.rocking_active = False
                self.time_remaining = 0

        self._notify_callbacks()

    async def start(self):
        self._shutdown = False
        self._connect_task = self.hass.async_create_task(self._connection_loop())

    async def stop(self):
        self._shutdown = True
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        if self._connect_task:
            self._connect_task.cancel()

    async def _connection_loop(self):
        while not self._shutdown:
            try:
                ble_device = self._get_device()
                if not ble_device:
                    self.is_connected = False
                    self._notify_callbacks()
                    await asyncio.sleep(10)
                    continue

                self.client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    "E-Priam",
                    max_attempts=2
                )
                
                self.is_connected = True
                
                status_char = self._get_characteristic(CHAR_STATUS, "notify")
                if not status_char:
                    status_char = self._get_characteristic(CHAR_STATUS)
                
                if status_char and ("notify" in status_char.properties or "indicate" in status_char.properties):
                    await self.client.start_notify(status_char, self._notification_handler)

                rock_char = self._get_characteristic(CHAR_ROCKING, "notify")
                if not rock_char:
                    rock_char = self._get_characteristic(CHAR_ROCKING)
                
                if rock_char and ("notify" in rock_char.properties or "indicate" in rock_char.properties):
                    _LOGGER.info("[Manager] Subscribing to Rocking characteristic for live hardware timer...")
                    await self.client.start_notify(rock_char, self._rocking_notification_handler)

                self._notify_callbacks()

                while self.client.is_connected and not self._shutdown:
                    await asyncio.sleep(5)
                    
            except Exception as e:
                _LOGGER.error(f"[Manager] Connection dropped/failed: {e}")
            finally:
                self.is_connected = False
                self._notify_callbacks()
                if self.client and self.client.is_connected:
                    await self.client.disconnect()
                await asyncio.sleep(5)

    async def set_drive_mode(self, mode: str):
        self.drive_mode = mode
        self._notify_callbacks()
        mode_map = {"Eco": 1, "Tour": 2, "Boost": 3}
        if mode not in mode_map: return False
        payload = bytearray([mode_map[mode]])
        return await self._write_to_char(CHAR_DRIVE_MODE, payload)

    async def set_rocking_state(self, is_on: bool):
        if is_on:
            # Stroller expects duration in seconds (16-bit integer, little-endian)
            duration_s = self.rocking_duration * 60
            dur_lo = duration_s & 0xFF
            dur_hi = (duration_s >> 8) & 0xFF
            
            # Payload format: [Command, Intensity, Duration_Lo, Duration_Hi]
            payload = bytearray([0x01, self.rocking_intensity, dur_lo, dur_hi])
            
            # Optimistically update
            self.rocking_active = True
            self.time_remaining = duration_s
        else:
            payload = bytearray([0x00])
            self.rocking_active = False
            self.time_remaining = 0
            
        success = await self._write_to_char(CHAR_ROCKING, payload)
        self._notify_callbacks()
        return success

    async def _write_to_char(self, char_uuid, payload: bytearray):
        if not self.is_connected or not self.client:
            _LOGGER.error("[Manager] Cannot write command, not connected.")
            return False
        try:
            char_obj = self._get_characteristic(char_uuid, "write")
            if not char_obj:
                char_obj = self._get_characteristic(char_uuid)
                
            if char_obj:
                requires_response = "write-without-response" not in char_obj.properties
                await self.client.write_gatt_char(char_obj, payload, response=requires_response)
                return True
            else:
                return False
        except Exception as e:
            return False

    async def async_send_raw_payload(self, hex_payload: str) -> bool:
        """Send a raw hex payload to the rocking characteristic for diagnostics."""
        try:
            payload = bytearray.fromhex(hex_payload)
        except ValueError as e:
            _LOGGER.error(f"[Manager] Invalid hex payload: {hex_payload} - {e}")
            return False
            
        _LOGGER.info(f"[Manager] Sending raw payload: {payload.hex()} to rocking characteristic")
        success = await self._write_to_char(CHAR_ROCKING, payload)
        self._notify_callbacks()
        return success

