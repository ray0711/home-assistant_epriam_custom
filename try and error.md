# The E-Priam Rocking Protocol: Development Recap

The Cybex E-Priam hardware is highly sensitive to payload length and byte order. Over the last several iterations, we have been testing various combinations of Write commands and Read/Notify parsers to align with the stroller's internal firmware. 

Here is a structured breakdown of every hypothesis, the payloads sent, the data received, and why it ultimately failed.

---

## Attempt 1: The Basic 3-Byte Payload & Software Timer
*   **Hypothesis:** The stroller expects a basic 3-byte start command using minutes and a 0–100% intensity scale. Because we did not know how to parse the hardware timer from the return payload, Home Assistant would manage the countdown locally.
*   **Write Payload Sent:** `[0x01, Duration (Minutes), Intensity (0-100)]`
*   **Result:** The stroller started rocking, but the 0–100 intensity scale caused unpredictable hardware scaling (the stroller actually expects a 1–3 discrete scale). Additionally, the hardware timer kept running after the Home Assistant software timer expired.

## Attempt 2: 4-Byte Payload (Total Seconds, Little-Endian)
*   **Hypothesis:** By analyzing the `python-priam` code, we learned the stroller *broadcasts* its remaining time as a 16-bit little-endian integer in seconds (`data[1] | (data[2] << 8)`). We assumed the *write* command must also require a 4-byte payload using total seconds.
*   **Write Payload Sent:** `[0x01, Intensity (1-3), Duration_Lo (Secs), Duration_Hi (Secs)]`
    *   *Example for 1 minute:* `[0x01, 0x01, 0x3C, 0x00]`
*   **Read Payload Received:** `01 00 01 01 01` -> `01 ff 00 01 01`
*   **Result:** A **256-second** countdown. Sending 4 bytes shifted the stroller's internal memory buffer. It interpreted the intensity byte as part of the timer, creating a misaligned countdown.

## Attempt 3: 4-Byte Payload (Total Seconds, Swapped Endianness)
*   **Hypothesis:** We assumed the 16-bit byte order in the write command was swapped (Big-Endian) compared to the read command.
*   **Write Payload Sent:** `[0x01, Intensity, Duration_Hi, Duration_Lo]`
    *   *Example for 1 minute:* `[0x01, 0x01, 0x00, 0x3C]`
*   **Read Payload Received:** `01 00 3c 01 3c` -> `01 ff 3b 01 3c`
*   **Result:** A **256-minute** (15,360 seconds) countdown. The stroller interpreted the `0x3C` (60) byte in the high-byte slot, multiplying the value exponentially. The dashboard switch bounced to "Off" due to an underlying `bleak` characteristic write rejection.

## Attempt 4: 3-Byte Write with Explicit Minutes/Seconds Read
*   **Hypothesis:** We reverted the write payload to the original 3 bytes but assumed the read payload was broadcasting explicit minutes and seconds rather than a 16-bit integer.
*   **Write Payload Sent:** `[0x01, Duration (Minutes), Intensity (1-3)]`
*   **Read Payload Received:** `01 02 3c 03 3c`, `01 00 78 01 78`
*   **Result:** When you kept the duration at 1 minute and changed the intensity slider from 1 to 2 to 3, the timer jumped to 256 minutes, 512 minutes, etc. The dashboard switch snapped back to "Off" instantly.

---

## The Current Protocol State

Your final tests proved that the `python-priam` read logic is absolutely correct:
1.  **Intensity** is encoded in the lower 4 bits of the first byte: `data[0] & 0xF`
2.  **Time Remaining (Seconds)** is a 16-bit little-endian integer in bytes 1 and 2: `data[1] | (data[2] << 8)`
3.  **Set Time (Seconds)** is a 16-bit little-endian integer in bytes 3 and 4: `data[3] | (data[4] << 8)`

**The Unsolved Variable:** 
If changing the *intensity* slider in Home Assistant causes the stroller's return *timer* to exponentially multiply (256, 512), it means the bytes in our Write command (`[0x01, Duration, Intensity]`) are still structurally crossed. The stroller is reading our intended Intensity byte and storing it inside its 16-bit duration register.