from importlib.metadata import version

import lab_devices


def test_version_matches_installed_metadata():
    assert lab_devices.__version__ == version("lab-devices")


def test_version_is_not_uninstalled_fallback():
    assert lab_devices.__version__ != "0.0.0.dev0"
