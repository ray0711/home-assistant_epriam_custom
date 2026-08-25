# Cybex E-Priam HA Integration: Developer Handover

This custom component establishes a continuous BLE connection to the Cybex E-Priam stroller, routing through Home Assistant's native Bluetooth stack (via ESPHome proxies). It bypasses the stroller's hardware timeouts by maintaining an active asynchronous loop, pushing real-time GATT notifications to Home Assistant entities.

## Core Architecture & State Management

The integration is built around a centralized `EPriamManager` (`manager.py`) to prevent proxy socket exhaustion. 

*   **Connection Loop:** A background `asyncio` task continuously scans the Bluetooth cache, establishes the `BleakClient`, and holds the socket open.
*   **Passive Entities:** `sensor.py`, `switch.py`, `select.py`, and `number.py` contain no BLE logic. They register callbacks with the manager and update their UI states instantly when the manager processes a hardware notification.
*   **Device Grouping:** All entities share a static `device_info` identifier (`cybex_epriam`) to group them neatly on the dashboard despite the stroller's rotating MAC address.

## The Reverse-Engineered Protocol

The most critical knowledge transfer involves the stroller's strict and undocumented byte structures. 

### 1. Battery / Status (`a1fc0102...`)
The stroller does not broadcast a standard 0-100% value; it broadcasts raw voltage. 
*   **Decoding:** Bytes 3 and 4 form a 16-bit little-endian integer. `voltage = (data[3] & 0xFF) * 2`. 
*   **Curve Mapping:** The stroller uses a 36V nominal 10S lithium-ion pack. Map the decivolts from 31.5V (0%) to 38.0V (100%).

### 2. Rocking Status Read / Notify (`a1fc0104...`)
The hardware broadcasts a 5-byte notification packet indicating its real-time rocking state.

| Byte Index | Purpose | Decoding Logic |
| :--- | :--- | :--- |
| `data[0]` | Run State & Errors | `0x01` = Running. `0x94` or `(data[0] ^ 128) == 20` = Brake not engaged error. |
| `data[1]` | Minutes Left | Direct integer (e.g., `0x02` = 2 minutes). |
| `data[2]` | Seconds Left | Direct integer (e.g., `0x3c` = 60 seconds). |
| `data[3]` | Current Intensity | `data[3] & 0xF` yields an integer from `1` to `3`. |
| `data[4]` | Original Set Minutes | Direct integer of the user's requested total time. |

### 3. Rocking Command Write (`a1fc0104...`)
The stroller is highly sensitive to payload length. Writing an oversized payload (e.g., 4 bytes instead of 3) causes the hardware buffer to misalign, resulting in the timer looping to 256 minutes.
*   **Format:** Exactly 3 bytes: `[Command, Duration_in_Minutes, Intensity]`. 
*   **Start Payload:** `[0x01, mins (int), intensity (1-3)]`
*   **Stop Payload:** `[0x00]`

## Known Hardware Quirks

*   **Duplicate GATT UUIDs:** The stroller's RN4871 BLE module exposes duplicate UUIDs in its GATT table. Blindly writing to the UUID string causes `bleak` to crash. The manager must iterate through `client.services`, locate the specific characteristic object containing the `write` or `notify` property, and use its explicit handle.
*   **Acknowledgment Drops:** Characteristics strictly require acknowledged writes (`response=True`). Using "Write Without Response" results in commands silently dropping into the void.