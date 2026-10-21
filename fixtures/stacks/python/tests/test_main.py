from app.main import root


def test_root():
    assert root() == {"ok": True}
