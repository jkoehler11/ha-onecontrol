# H-Bridge Command Format Research

## Summary
The H-Bridge command format (0x41) is **declared but not implemented** in the current codebase. Cover/slide/awning control is intentionally state-only for safety reasons. The command type exists in the protocol but no builder method exists.

---

## 1. H-Bridge Command Declaration

### Location: [const.py](custom_components/ha_onecontrol/const.py#L94)
```python
# Command Types (for outbound command builder)
CMD_ACTION_HBRIDGE = 0x41
CMD_ACTION_GENERATOR = 0x42
CMD_ACTION_DIMMABLE = 0x43
CMD_ACTION_RGB = 0x44
CMD_ACTION_HVAC = 0x45
```

### Location: [commands.py](custom_components/ha_onecontrol/protocol/commands.py#L26)
```python
class CommandBuilder:
    """Construct OneControl MyRvLink command byte arrays."""
    
    CMD_GET_DEVICES = 0x01
    CMD_GET_DEVICES_METADATA = 0x02
    CMD_ACTION_SWITCH = 0x40
    CMD_ACTION_HBRIDGE = 0x41  # ← DECLARED BUT NO BUILDER METHOD
    CMD_ACTION_GENERATOR = 0x42
    CMD_ACTION_DIMMABLE = 0x43
    CMD_ACTION_RGB = 0x44
    CMD_ACTION_HVAC = 0x45
```

**Status:** No `build_action_hbridge()` method exists. The constant is defined but the command builder is not implemented.

---

## 2. H-Bridge Status Parsing (Receive Path)

### Location: [protocol/events.py](custom_components/ha_onecontrol/protocol/events.py#L213-L230)

#### CoverStatus Dataclass:
```python
@dataclass
class CoverStatus:
    """H-Bridge / cover status (event 0x0D/0x0E).

    INTERNALS.md § Cover/Slide/Awning:
        STATE-ONLY.  No commands (safety: no limit switches, 19-39A motors).
        Legacy host events use 0xC0=stopped, 0xC2=opening, 0xC3=closing.
        IDS-CAN DEVICE_STATUS commonly reports 0x00 for stopped/idle.
    """

    table_id: int = 0
    device_id: int = 0
    status: int = 0
    position: int | None = None  # 0-100 or None if 0xFF

    @property
    def ha_state(self) -> str:
        """HA-compatible state string."""
        return {0xC2: "opening", 0xC3: "closing", 0xC0: "stopped", 0x00: "stopped"}.get(
            self.status, "unknown"
        )
```

#### Status Values (Host Events):
| Status Byte | Meaning |
|-------------|---------|
| 0xC0        | Stopped |
| 0xC2        | Opening |
| 0xC3        | Closing |
| 0x00        | Stopped (IDS-CAN DEVICE_STATUS) |

#### Status Parsing (Event 0x0D/0x0E):
```python
def parse_cover_status(data: bytes) -> CoverStatus | None:
    """Parse H-Bridge status (0x0D/0x0E).

    INTERNALS.md § Cover/Slide/Awning:
      STATE-ONLY — no control commands published.
      Position: 0xFF = unavailable.
    """
    if len(data) < 4:
        return None
    pos = data[4] if len(data) > 4 else None
    if pos is not None and pos == 0xFF:
        pos = None
    return CoverStatus(
        table_id=data[1],
        device_id=data[2],
        status=data[3],
        position=pos,
    )
```

**Frame Format:**
```
[EventType:1B] [TableId:1B] [DeviceId:1B] [Status:1B] [Position:1B (optional)]
     0x0D/0E        table_id      device_id      0xC0/C2/C3    0-100 or 0xFF
```

---

## 3. Cover Status Byte Constants

### Location: [const.py](custom_components/ha_onecontrol/const.py#L141-L147)
```python
# Cover status byte values (state-only, no commands — INTERNALS.md § Cover)
# ---------------------------------------------------------------------------
COVER_STOPPED = 0xC0
COVER_OPENING = 0xC2
COVER_CLOSING = 0xC3
```

---

## 4. IDS-CAN H-Bridge Decoding

### Location: [coordinator.py](custom_components/ha_onecontrol/coordinator.py#L2187-L2195)
```python
def _dispatch_can_entity(self, wire: "IdsCanWireFrame", decoded: "IdsCanDecodedPayload | None") -> None:
    """Dispatch decoded IDS-CAN frames to internal state maps."""
    
    # ... [earlier code] ...
    
    if dev_type == 33:  # H-Bridge / cover (slide-out, awning)
        status = payload[0] if len(payload) >= 1 else 0xC0
        pos: int | None = payload[1] if len(payload) >= 2 else None
        if pos == 0xFF:
            pos = None
        event = CoverStatus(table_id=0, device_id=src, status=status, position=pos)
        self.covers[key] = event

    elif dev_type == 30:  # Relay (light, switch)
        status_byte = payload[0] if len(payload) >= 1 else 0x00
        # ... [relay handling] ...
```

**IDS-CAN Device Type 33** = H-Bridge / cover / slide-out / awning

---

## 5. Safety Notes & Intentional State-Only Design

### Location: [cover.py](custom_components/ha_onecontrol/cover.py#L1-L12)
```python
"""Cover platform for OneControl BLE integration.

IMPORTANT: Covers are STATE-ONLY — no open/close/stop commands are sent.
Per INTERNALS.md safety decision:
  "Cover control was intentionally disabled... RV awnings and slides have
   no automatic safety mechanisms. The 19A/39A H-bridge motors could cause
   damage or injury without manual supervision."

Creates Cover entities that show the current state (opening/closing/stopped)
but do NOT allow control via Home Assistant.

Reference: INTERNALS.md § Cover / Slide / Awning
"""
```

### Motor Specifications (From Documentation):
- **Motor Current:** 19A/39A H-bridge motors
- **Safety Issue:** No limit switches, no automatic safety mechanisms
- **Risk:** Damage or injury without manual supervision
- **Result:** Cover control is disabled at the Home Assistant integration level

### Location: [sensor.py](custom_components/ha_onecontrol/sensor.py#L618)
```python
      "19A/39A H-bridge motors, no limit switches — no automatic safety."
```

---

## 6. Cover Entity Implementation (State-Only)

### Location: [cover.py](custom_components/ha_onecontrol/cover.py#L80-L165)
```python
class OneControlCover(CoordinatorEntity[OneControlCoordinator], CoverEntity):
    """Cover entity — state-only, no control commands.

    Shows opening / closing / stopped state from the H-Bridge status event.
    Position is exposed when available (0xFF means unknown).
    """

    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.AWNING
    _attr_supported_features = CoverEntityFeature(0)  # No control features

    # ... [entity properties] ...

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Intentionally not implemented — safety."""
        _LOGGER.warning("Cover open command blocked — safety: no limit switches")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Intentionally not implemented — safety."""
        _LOGGER.warning("Cover close command blocked — safety: no limit switches")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Intentionally not implemented — safety."""
        _LOGGER.warning("Cover stop command blocked — safety: no limit switches")
```

---

## 7. Event Types (Inbound H-Bridge Events)

### Location: [const.py](custom_components/ha_onecontrol/const.py#L79-L80)
```python
EVENT_HBRIDGE_1 = 0x0D   # H-Bridge status event (legacy host)
EVENT_HBRIDGE_2 = 0x0E   # H-Bridge status event (variant)
```

---

## 8. Command Wire Format (All Commands)

### Location: [protocol/commands.py](custom_components/ha_onecontrol/protocol/commands.py#L1-L12)
```python
"""Command builder for OneControl MyRvLink protocol.

Builds raw command byte arrays for COBS-encoding and BLE transmission.
A monotonic ``command_id`` counter ensures each command has a unique 16-bit
sequence number (LE order) for correlating ack events (0x02).

Wire format for all commands:
  [CmdId_LSB][CmdId_MSB][CommandType][...payload...]

Reference: INTERNALS.md § Command Building, MyRvLinkCommandBuilder.kt
"""
```

### General Command Structure:
```
[CmdId_LSB] [CmdId_MSB] [CommandType] [Payload...]
   1 byte       1 byte       1 byte      variable
   LE order               0x41 for H-Bridge
```

---

## 9. Similar Command Implementations (For Reference)

### ActionSwitch (0x40) — Simple Example:
```python
def build_action_switch(self, device_table_id: int, state: bool, device_ids: list[int]) -> bytes:
    """Build an ActionSwitch command."""
    cid = self._next_id()
    state_byte = 0x01 if state else 0x00
    header = (
        self._id_bytes(cid)
        + bytes([self.CMD_ACTION_SWITCH, device_table_id & 0xFF, state_byte])
    )
    return header + bytes(d & 0xFF for d in device_ids)
    # → Result: 6 bytes for single device
```

### ActionGenerator (0x42) — Start/Stop Example:
```python
def build_action_generator(self, device_table_id: int, device_id: int, run: bool) -> bytes:
    """Build an ActionGeneratorGenie command (6 bytes)."""
    cid = self._next_id()
    state_byte = 0x01 if run else 0x00
    return (
        self._id_bytes(cid)
        + bytes([
            self.CMD_ACTION_GENERATOR,
            device_table_id & 0xFF,
            device_id & 0xFF,
            state_byte,
        ])
    )
    # → Result: 6 bytes
```

### ActionDimmable (0x43) — With Parameters:
```python
def build_action_dimmable(self, device_table_id: int, device_id: int, brightness: int) -> bytes:
    """Build an ActionDimmable command (8 bytes)."""
    cid = self._next_id()
    mode = 0x00 if brightness == 0 else 0x01
    return (
        self._id_bytes(cid)
        + bytes([
            self.CMD_ACTION_DIMMABLE,
            device_table_id & 0xFF,
            device_id & 0xFF,
            mode,
            min(max(brightness, 0), 255),
            0x00,  # reserved
        ])
    )
    # → Result: 8 bytes
```

---

## 10. Motor Control References (DTC Codes)

### Location: [protocol/dtc_codes.py](custom_components/ha_onecontrol/protocol/dtc_codes.py#L1712-L1713)
```python
1712: "MOTOR_RETRACT_SOFTSTOP_NOT_CONFIGURED",
1713: "MOTOR_EXTEND_SOFTSTOP_NOT_CONFIGURED",
```

These DTC codes indicate motor direction control:
- **EXTEND** — Open/extend the cover (e.g., awning extend)
- **RETRACT** — Close/retract the cover (e.g., awning retract)

The "SOFTSTOP" concept suggests the motors support gradual deceleration when reaching endpoints.

---

## 11. Protocol Documentation References

### Location: [docs/TECH_SPEC.md](docs/TECH_SPEC.md#L85)
```markdown
MyRvLink event byte identifiers include (non-exhaustive):
- `0x01` gateway info, `0x02` command response, `0x05/0x06` relay, `0x08` dimmable, `0x09` RGB,
- `0x0B` HVAC, `0x0C/0x1B` tank, `0x0D/0x0E` h-bridge, `0x0F` hour meter, `0x20` RTC.
```

### Command Types Reference:
```markdown
Key command types:
- `0x01` GetDevices
- `0x02` GetDevicesMetadata
- `0x40` switch action
- `0x41` h-bridge action
- `0x42` generator action
- `0x43` dimmable action
- `0x44` RGB action
- `0x45` HVAC action
```

---

## 12. Function Names (Covers/Slides)

### Location: [protocol/function_names.py](custom_components/ha_onecontrol/protocol/function_names.py#L96-L137)
```python
    # Slides
    96: "Slide",
    97: "Main Slide",
    98: "Bedroom Slide",
    99: "Galley Slide",
    100: "Kitchen Slide",
    101: "Closet Slide",
    102: "Optional Slide",
    103: "Door Side Slide",
    104: "Off Door Slide",
    133: "Bunk Slide",
    134: "Bed Slide",
    135: "Wardrobe Slide",
    136: "Entertainment Slide",
    137: "Sofa Slide",
    148: "Slide In Slide",
    299: "Slide If Equip",
    315: "Bathroom Slide",
```

---

## Key Findings

### ✓ Implemented:
1. **Status parsing** for H-Bridge events (0x0D/0x0E)
2. **CoverStatus dataclass** with position tracking
3. **Cover entity** for Home Assistant (state-only)
4. **IDS-CAN decoding** for device type 33 (H-Bridge)
5. **Status bytes:** 0xC0 (stopped), 0xC2 (opening), 0xC3 (closing), 0x00 (stopped)

### ✗ NOT Implemented:
1. **build_action_hbridge()** command builder
2. **H-Bridge control command format** (0x41 payload structure)
3. **Cover control methods** (open/close/stop intentionally disabled for safety)

### Motor Control Hints:
- Motor directions: **EXTEND** (open/extend) and **RETRACT** (close/retract)
- Soft-stop support indicated by DTC codes
- Position feedback: 0-100% or unavailable (0xFF)
- No duration/speed parameters exposed in current implementation

### Safety Rationale:
- 19A/39A motors with no limit switches
- No automatic safety mechanisms
- Risk of damage/injury without manual supervision
- Cover control deliberately disabled at integration level

---

## Protocol Gap

**The H-Bridge command format (0x41) is documented in the protocol but the implementation is intentionally incomplete.** 

This is a deliberate design decision based on safety constraints. To implement cover control, you would need to:

1. Define the command payload structure (likely similar to ActionGenerator 0x42 or ActionSwitch 0x40)
2. Add a `build_action_hbridge()` method to `CommandBuilder`
3. Add direction, duration, and speed parameters
4. Enable control methods in the Cover entity
5. **Accept the safety risk** of controlling high-current motors without limit switches

The command type (0x41) is already allocated in the protocol, but the device-side behavior and Android app implementation remain the source of truth for the actual payload format.

