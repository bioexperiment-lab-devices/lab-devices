import httpx
import pytest

from lab_devices.transport import Transport
from tests.fakelab import FakeLab


@pytest.fixture
def lab_transport():
    fake = FakeLab()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    yield fake, Transport(client)
    # AsyncClient cleanup handled per-test via the returned client is not needed for MockTransport.
