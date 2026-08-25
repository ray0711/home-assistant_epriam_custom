# Cybex E-Priam Continuous Integration for Home Assistant

This Home Assistant custom component establishes a continuous BLE connection to the Cybex E-Priam electric stroller (routing through Home Assistant's native Bluetooth stack/ESPHome BLE proxies). By running a persistent background connection loop, it bypasses the stroller's default hardware timeout limits, providing real-time status tracking and dashboard controls for rocking.

> [!CAUTION]
> ### ⚠️ SAFETY DISCLAIMER & WARRANTY WARNING
> **THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.**
>
> Controlling heavy, motorized baby transport hardware via reverse-engineered Bluetooth protocols carries inherent risks. By using this integration, you agree that:
> 1. The stroller, BLE module, battery, or adjacent devices **might break, malfunction, or literally explode**.
> 2. You assume **all liability** for the safety of any child placed in the stroller.
> 3. The rocking function **MUST NOT** be engaged unless the physical foot brake is fully locked, the stroller is on flat ground, and a supervising adult is in close proximity.
> 4. Use this software entirely at your own risk.

---

## Features
* **Track Battery Status**: Displays the stroller's current battery percentage.
* **Enable Rocking**: Turn rocking on or off, set a timer duration, and choose the speed intensity (Low, Medium, High). Will warn you with a toast notification if you attempt to start rocking without the brake engaged.
* **Set Driving Mode**: Switch between Eco, Tour, and Boost power assist levels.
* **Real-time Status Entity**: Shows the current state of the stroller (Connected, Rocking, Stopped, or Brake Not Engaged).

---

## Upstream References

This project is built upon the protocol reverse-engineering work and codebase implementations from the following upstream projects:
* **[vincegio/python-priam](https://github.com/vincegio/python-priam)**: The original Python proof-of-concept repository that reverse-engineered the BLE connection logic, battery voltage mapping, and status structures.
* **[owanvik/esPriam32](https://github.com/owanvik/esPriam32)**: An ESP32-C6 firmware bridge that mapped the core GATT handles, rocking control commands, and auto-renew patterns.
