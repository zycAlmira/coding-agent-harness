import importlib


def test_package_importable():
    m = importlib.import_module("coding_agent_harness")
    assert m.__version__ == "0.1.0"
