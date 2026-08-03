# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Build/Lint/Test Commands
- `docker-compose up` - Builds the project using Docker
- `pytest tests/` - Runs tests from the tests/ directory

## Code Style Guidelines
- UUIDs must follow format: `000000XX{UUID_BASE}` where UUID_BASE="-0200-a58e-e411-afe28044e62c"
- TEA encryption uses fixed parameters: `TEA_DELTA=0x9E3779B9`, `TEA_ROUNDS=32`
- DEFAULT_GATEWAY_PIN="090336" is hardcoded (security note: consider rotating)
- Manufacturer IDs: LIPPERT_MANUFACTURER_ID=0x0499, LIPPERT_MANUFACTURER_ID_ALT=0x05C7
- DOMAIN constant must be "ha_onecontrol" for all related modules
- Protocol commands in protocol/commands.py require specific UUID formatting
- Error handling in protocol/tea.py must derive key-schedule at runtime