from local_home_devices_mcp.composition import (
    effective_response_limit,
    encoded_response_bytes,
)
from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.manifests import normalize_catalog
from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS


def test_response_limit_is_capability_specific_and_hard_capped():
    manifest = normalize_catalog(MOCK_MANIFESTS)["mock_get_state"]
    settings = Settings.for_mock()
    assert effective_response_limit(manifest, settings) == 32 * 1024
    assert encoded_response_bytes({"value": "x" * 100}) < 32 * 1024
