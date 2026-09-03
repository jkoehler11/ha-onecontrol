from __future__ import annotations


def normalize_device_name(name: str | None, key: str) -> str:
    """Return a friendly device name, avoiding generic Function 0x labels."""
    if name is None or name.startswith("Function 0x"):
        return f"Device {key.upper()}"
    return name
