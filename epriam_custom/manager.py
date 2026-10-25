import logging
import asyncio
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
    async_register_callback,
)
from homeassistant.core import HomeAssistant

from .const import CHAR_STATUS, CHAR_ROCKING, CHAR_DRIVE_MODE, CYBEX_MANUFACTURER_ID

SERVICE_UUID = "a1fc0101-78d3-40c2-9b6f-3c5f7b2797df"
# Safety net only; normally we are woken by advertisements / disconnects.
FALLBACK_POLL_SECONDS = 60
RECONNECT_BACKOFF_SECONDS = 2
MAX_RECONNECT_BACKOFF_SECONDS = 60

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
        self.status = "Disconnected"
        self._rocking_error_received = None
        self._rocking_started_received = None
        
        self._callbacks = []
        self._connect_task = None
        self._shutdown = False
        self._adv_event = asyncio.Event()
        self._disconnect_event = asyncio.Event()
        self._unsub_bluetooth = []

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
            if SERVICE_UUID in discovery_info.service_uuids:
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
        _LOGGER.debug(f"[Manager] Battery/Status Notify Payload: {data.hex()}")
        if len(data) >= 4:
            voltage = (data[3] & 0xFF) * 2
            pct = int(((voltage - 315) * 100) / 65)
            self.battery_level = max(0, min(100, pct))
        self._notify_callbacks()

    def _rocking_notification_handler(self, sender, data: bytearray):
        _LOGGER.debug(f"[Manager] Rocking Notify Payload: {data.hex()}")
        if len(data) >= 5:
            intensity_raw = data[0] & 0xF
            
            # 16-bit integer (little endian) in seconds
            time_left = (data[1] & 255) | ((data[2] & 255) << 8)
            
            self.time_remaining = time_left
            self.rocking_active = (time_left > 0 or intensity_raw > 0)
            
            if 1 <= intensity_raw <= 3:
                # Map stroller intensity (1=Fastest, 3=Slowest) back to UI (1=Low/Slowest, 3=High/Fastest)
                self.rocking_intensity = 4 - intensity_raw
            
            if data[0] == 0x94: # 148 ^ 128 = 20 (Brake not engaged)
                _LOGGER.warning("[Manager] Stroller reported: Brake not engaged. Rocking cannot start.")
                self.status = "Brake Not Engaged"
                self.rocking_active = False
                self.time_remaining = 0
                if self._rocking_error_received:
                    self._rocking_error_received.set()
            elif self.rocking_active:
                self.status = "Rocking"
                if self._rocking_started_received:
                    self._rocking_started_received.set()
            else:
                self.status = "Stopped"

        self._notify_callbacks()

    def _on_advertisement(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ):
        """Wake the connection loop as soon as any proxy/adapter sees the pram."""
        if not self.is_connected:
            self._adv_event.set()

    async def start(self):
        self._shutdown = False
        # One matcher per identifying trait (matchers are ANDed internally).
        for matcher in (
            BluetoothCallbackMatcher(manufacturer_id=CYBEX_MANUFACTURER_ID, connectable=True),
            BluetoothCallbackMatcher(service_uuid=SERVICE_UUID, connectable=True),
            BluetoothCallbackMatcher(local_name="Priam*", connectable=True),
        ):
            self._unsub_bluetooth.append(
                async_register_callback(
                    self.hass,
                    self._on_advertisement,
                    matcher,
                    BluetoothScanningMode.ACTIVE,
                )
            )
        # Background task: the loop never finishes, so it must not be tracked
        # by bootstrap/startup (otherwise HA waits for it until the stage timeout).
        self._connect_task = self.hass.async_create_background_task(
            self._connection_loop(), "epriam_custom connection loop"
        )

    async def stop(self):
        self._shutdown = True
        for unsub in self._unsub_bluetooth:
            unsub()
        self._unsub_bluetooth.clear()
        self._adv_event.set()
        self._disconnect_event.set()
        if self._connect_task:
            self._connect_task.cancel()
            await asyncio.gather(self._connect_task, return_exceptions=True)
            self._connect_task = None
        await self._safe_disconnect()

    async def _safe_disconnect(self):
        if self.client and self.client.is_connected:
            try:
                await self.client.disconnect()
            except Exception:
                _LOGGER.debug("[Manager] disconnect failed", exc_info=True)

    async def _connection_loop(self):
        backoff = RECONNECT_BACKOFF_SECONDS
        while not self._shutdown:
            failed = False
            idle = False
            try:
                ble_device = self._get_device()
                if not ble_device:
                    self.is_connected = False
                    self._notify_callbacks()
                    # Event driven: wait for an advertisement (fallback poll).
                    self._adv_event.clear()
                    try:
                        await asyncio.wait_for(
                            self._adv_event.wait(), FALLBACK_POLL_SECONDS
                        )
                    except asyncio.TimeoutError:
                        pass
                    idle = True  # already waited; skip the reconnect delay
                    continue

                # Per-attempt event so a late callback from an old client
                # cannot end a newer connection.
                disconnect_event = self._disconnect_event = asyncio.Event()
                self.client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    "E-Priam",
                    disconnected_callback=lambda _client: disconnect_event.set(),
                    max_attempts=2
                )
                
                self.is_connected = True
                self.status = "Connected"
                backoff = RECONNECT_BACKOFF_SECONDS
                
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

                if self.client.is_connected:
                    await disconnect_event.wait()
                    
            except Exception as e:
                failed = True
                _LOGGER.warning(f"[Manager] Connection dropped/failed: {e}")
            finally:
                self.is_connected = False
                self.status = "Disconnected"
                self._notify_callbacks()
                await self._safe_disconnect()
                if not self._shutdown and not idle:
                    if failed:
                        # Exponential backoff, but wake early on a fresh advertisement.
                        self._adv_event.clear()
                        try:
                            await asyncio.wait_for(self._adv_event.wait(), backoff)
                        except asyncio.TimeoutError:
                            pass
                        backoff = min(backoff * 2, MAX_RECONNECT_BACKOFF_SECONDS)
                    else:
                        await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)

    async def set_drive_mode(self, mode: str):
        self.drive_mode = mode
        self._notify_callbacks()
        mode_map = {"Eco": 1, "Tour": 2, "Boost": 3}
        if mode not in mode_map: return False
        payload = bytearray([mode_map[mode]])
        return await self._write_to_char(CHAR_DRIVE_MODE, payload)

    async def set_rocking_state(self, is_on: bool):
        from homeassistant.exceptions import HomeAssistantError

        if is_on:
            # Stroller expects duration in seconds (16-bit integer, little-endian)
            duration_s = self.rocking_duration * 60
            dur_lo = duration_s & 0xFF
            dur_hi = (duration_s >> 8) & 0xFF
            
            # Map UI intensity (1=Low/Slowest, 3=High/Fastest) to stroller command byte (0x03=Slowest, 0x01=Fastest)
            stroller_intensity = 4 - self.rocking_intensity
            
            # Payload format: [Intensity_Command, Duration_Lo, Duration_Hi]
            payload = bytearray([stroller_intensity, dur_lo, dur_hi])
            _LOGGER.debug(f"[Manager] Writing rocking command payload: {payload.hex()}")
            
            self._rocking_error_received = asyncio.Event()
            self._rocking_started_received = asyncio.Event()
            
            # Optimistically update
            self.rocking_active = True
            self.time_remaining = duration_s
            self._notify_callbacks()
            
            success = await self._write_to_char(CHAR_ROCKING, payload)
            if not success:
                self.rocking_active = False
                self.time_remaining = 0
                self.status = "Stopped"
                self._notify_callbacks()
                raise HomeAssistantError("Failed to write rocking command to stroller.")

            # Wait for response from stroller
            started_task = asyncio.create_task(self._rocking_started_received.wait())
            error_task = asyncio.create_task(self._rocking_error_received.wait())
            try:
                await asyncio.wait(
                    {started_task, error_task},
                    timeout=1.5,
                    return_when=asyncio.FIRST_COMPLETED
                )
            except Exception as e:
                _LOGGER.error(f"[Manager] Error waiting for status: {e}")
            finally:
                started_task.cancel()
                error_task.cancel()

            if self._rocking_error_received.is_set():
                self.rocking_active = False
                self.time_remaining = 0
                self.status = "Brake Not Engaged"
                self._notify_callbacks()
                raise HomeAssistantError("Brake not engaged! Engage brake to start rocking.")
            
            return True
        else:
            payload = bytearray([0x00])
            _LOGGER.debug(f"[Manager] Writing rocking command payload: {payload.hex()}")
            self.rocking_active = False
            self.time_remaining = 0
            success = await self._write_to_char(CHAR_ROCKING, payload)
            self.status = "Stopped"
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

