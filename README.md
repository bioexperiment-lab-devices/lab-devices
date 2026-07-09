# lab_devices

Async Python library to discover and manage lab devices — peristaltic pumps,
distribution valves, and densitometers — over the SerialHop / lab-bridge API.

## Install

    pip install bioexperiment-lab-devices    # import as: import lab_devices

For development (runtime + dev deps):

    poetry install --all-extras
    # or, without Poetry:
    pip install -e ".[dev]"

## Core usage (host + port)

```python
import asyncio
from lab_devices import LabClient

async def main():
    async with LabClient("chisel", 8089) as lab:
        pump = lab.pump(1)
        job = await pump.dispense(volume_ml=10, speed_ml_min=3.0)
        result = await job.result()
        print(result.dispensed_ml)

asyncio.run(main())
```

## Server-only discovery (inside labnet)

```python
from lab_devices.discovery import LabRegistry

async with LabRegistry() as reg:            # LAB_DEVICES_DISCOVERY_URL overrides the endpoint
    print(await reg.list_labs())
    lab = await reg.connect("khamit_desktop")
    async with lab:
        await lab.densitometer(1).measure()
```

Discovery uses the internal, unauthenticated roster endpoint and needs no token.
It only works from inside the lab-bridge network.

## Development

    poetry run pytest        # hermetic; no hardware needed
    poetry run mypy
    poetry run ruff check .
