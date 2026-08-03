from pathlib import Path

import pytest

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_states_the_platform_honestly():
    assert "macOS" in README.read_text()


def test_readme_shows_the_install_command():
    assert "./install.sh" in README.read_text()


def test_readme_documents_every_mode():
    text = README.read_text()

    for mode in ("off", "notify", "voice", "both"):
        assert f"`{mode}`" in text


@pytest.mark.xfail(reason="LICENSE pending: copyright holder undecided")
def test_licence_exists():
    assert (README.parent / "LICENSE").exists()
