import pytest

_EXTERNAL = ("MESHY_API_KEY", "GEMINI_API_KEY", "PRINTER_IP", "PRINTER_SERIAL", "PRINTER_ACCESS_CODE", "ORCA_SLICER_BIN")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every test runs offline in mock mode, whatever the shell environment holds."""
    monkeypatch.setenv("FACTORY_MOCK", "1")
    for key in _EXTERNAL:
        monkeypatch.delenv(key, raising=False)
    from factory import printer

    monkeypatch.setattr(printer, "_printer", None)


@pytest.fixture(scope="session")
def nametag_artifact(tmp_path_factory):
    from factory.cad import build_template

    return build_template("nametag", {"text": "AKSHAYA"}, tmp_path_factory.mktemp("nametag"))
