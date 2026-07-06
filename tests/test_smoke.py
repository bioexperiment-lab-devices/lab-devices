import lab_devices


def test_version_exposed():
    assert isinstance(lab_devices.__version__, str)
    assert lab_devices.__version__
