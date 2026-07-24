# Invisible-4-eyes-Calibration-4

Calibration platform for multi-board feedback collection and 3D DensePose visualization.

## Project Goals

- Integrate real-time feedback from 4 ESP32-S3 Nano boards.
- Improve calibration stability and observability.
- Add proper DensePose display in 3D for better spatial inspection.

## Phase Focus (Current)

This calibration phase adds denser device feedback loops and introduces a 3D DensePose rendering pipeline for easier debugging and alignment.

## Planned Architecture

- `firmware/`: ESP32-S3 board code and communication handlers.
- `ingest/`: host-side receiver for board telemetry.
- `calibration/`: calibration logic, fusion, and scoring.
- `visualization/`: 3D DensePose display and scene controls.

## Quick Start

1. Clone the repository.
2. Add your board firmware under `firmware/`.
3. Implement host telemetry receiver under `ingest/`.
4. Start calibration routines and connect visualization.

## Development Notes

- Use consistent timestamping across all 4 boards.
- Keep device IDs stable and explicit.
- Log raw and calibrated streams for replay.

## License

Released under the MIT License. See `LICENSE` for details.
