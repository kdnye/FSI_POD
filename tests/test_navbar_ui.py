from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_help_link_points_to_approved_external_support():
    template = (_repo_root() / "templates" / "base.html").read_text()

    assert 'href="https://support.freightservicesinc.com/help"' in template
    assert 'target="_blank"' in template
    assert 'rel="noopener noreferrer"' in template


def test_account_dropdown_contains_expected_menu_items():
    template = (_repo_root() / "templates" / "base.html").read_text()

    assert "Active Load Board" in template
    assert "POD History" in template
    assert 'data-account-menu-toggle' in template
    assert 'data-account-menu-list' in template
    assert 'href="/account/profile"' in template
    assert 'href="/account/settings"' in template
    assert 'href="/auth/logout"' in template


def test_navbar_js_supports_open_close_and_keyboard_navigation():
    script = (_repo_root() / "static" / "js" / "navbar.js").read_text()

    assert "toggle.addEventListener('click'" in script
    assert "event.key === 'Escape'" in script
    assert "event.key === 'ArrowDown'" in script
    assert "event.key === 'ArrowUp'" in script
    assert "event.key === 'Home'" in script
    assert "event.key === 'End'" in script
    assert "document.addEventListener('click'" in script
