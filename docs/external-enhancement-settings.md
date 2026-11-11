# External enhancement settings

An optional external DLSS5 session adds **DLSS5 enhancement** to **F1 → Graphics**. The native menu shows its status and ten basic controls; **Advanced enhancement** reveals nine more. It uses the session adapter to apply and save changes. F10 does not open a separate control window.

**Reset DLSS5 settings** restores all 19 enhancement settings with one activation: Enter, the controller's confirm button, or a mouse click. Left and Right do nothing on this action. It is unavailable while the helper is unavailable or another change is applying. Reset uses one complete settings request and the existing acknowledgement and persistence path. Its optional `reset=1` marker is accepted only with the complete factory snapshot and forces exact values, including saved float values that would round to the same percentage; ordinary edits retain untouched precision. It does not reset graphics options, controls, or the player's game profile. Changes to model settings can briefly rebuild the enhancement model.

These defaults follow the external layer's `ShmInitDefaults`, with the adapter's existing 50% model resolution and native-detail composition defaults:

| Setting | Default |
| --- | --- |
| Enabled / Apply model result | On / On |
| Comparison / Split | Off / 50% |
| Detail / Colour / Sharpness | 100% / 100% / 0% |
| Intensity / Local tone / Local structure | 100% / 100% / 100% |
| Skin structure / Automatic skin mask | Follow local / On |
| Style / Preset | Default / 0 |
| Model resolution | 50% |
| Raw model output / Edit composition | Off / Native + edit |
| Motion quality / Motion grid | Balanced / 4 pixels |

`scripts/dlss5_api.py` defines `DEFAULT_SETTINGS`, used both before loading saved preferences at startup and by tests of the reset contract. The native defaults in `gpu/vk/dlss5_controls.h` use integer UI units; `tests/test_dlss5_menu.py` compares every key and value across the two definitions. The client and adapter tests cover a single full reset request, acknowledgement, input gating and persisted values without requiring the game or an external model.
