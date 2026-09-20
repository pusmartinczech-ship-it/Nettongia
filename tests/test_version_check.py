import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpdf_editor.version_check import (
    ReleaseInfo,
    is_newer,
    parse_release,
    version_tuple,
)


def test_versions_are_compared_without_v_prefix() -> None:
    assert version_tuple("v0.19.0") == (0, 19, 0)
    assert is_newer("0.19.0", "v0.20.0")
    assert not is_newer("0.19.0", "0.19.0")
    assert not is_newer("0.20.0", "0.19.9")


def test_release_parser_selects_portable_asset() -> None:
    payload = json.dumps(
        {
            "tag_name": "v0.20.0",
            "html_url": "https://github.com/pusmartinczech-ship-it/Nettongia/releases/tag/v0.20.0",
            "assets": [
                {
                    "name": "Nettongia_PDF_Editor_0.20.0-portable-release.zip",
                    "browser_download_url": "https://github.com/pusmartinczech-ship-it/Nettongia/releases/download/v0.20.0/portable.zip",
                }
            ],
        }
    )
    assert parse_release(payload) == ReleaseInfo(
        "0.20.0",
        "https://github.com/pusmartinczech-ship-it/Nettongia/releases/tag/v0.20.0",
        "https://github.com/pusmartinczech-ship-it/Nettongia/releases/download/v0.20.0/portable.zip",
    )


def test_release_parser_rejects_untrusted_page_urls() -> None:
    payload = json.dumps({"tag_name": "v0.20.0", "html_url": "https://evil.example/release"})
    assert parse_release(payload).page_url == "https://github.com/pusmartinczech-ship-it/Nettongia/releases"


def test_invalid_versions_are_rejected() -> None:
    with pytest.raises(ValueError):
        version_tuple("latest")


@pytest.mark.parametrize("tag", ["v1.0.0-beta", "1.0.0+build", "1", "", "1.2.3.4"])
def test_non_stable_tags_rejected(tag):
    with pytest.raises(ValueError):
        version_tuple(tag)


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_unpublished_releases_rejected(flag):
    with pytest.raises(ValueError):
        parse_release(json.dumps({"tag_name": "v1.0.0", flag: True}))


def test_other_github_repository_is_not_trusted():
    release = parse_release(json.dumps({
        "tag_name": "v1.0.0", "html_url": "https://github.com/other/repo/releases/tag/v1.0.0",
        "assets": [{"name": "portable.zip", "browser_download_url": "https://github.com/other/repo/file"}],
    }))
    assert release.page_url.endswith("/Nettongia/releases")
    assert release.portable_asset_url is None


def test_transport_is_bounded_and_has_no_document_data(monkeypatch):
    from openpdf_editor import version_check as module
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            assert limit == module.MAX_RESPONSE_BYTES + 1
            return b'{"tag_name":"v1.0.0"}'
    def request(req, timeout):
        assert req.full_url == module.CURRENT_RELEASE_API
        assert req.data is None
        assert timeout == 4.0
        return Response()
    monkeypatch.setattr(module, "urlopen", request)
    assert module.fetch_latest_release().version == "1.0.0"


def test_oversized_metadata_is_rejected(monkeypatch):
    from openpdf_editor import version_check as module
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b"x" * limit
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="size limit"):
        module.fetch_latest_release()


@pytest.fixture
def update_window(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from openpdf_editor import main_window as module
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(module, "QSettings", lambda *args: settings)
    window = module.MainWindow()
    window._maybe_save_changes = lambda: True
    yield app, window
    window.close()
    window._update_pool.waitForDone(6000)
    app.processEvents()
    window.deleteLater()
    app.processEvents()


def test_startup_throttle_disable_and_manual_override(update_window, monkeypatch):
    _, window = update_window
    started = []
    monkeypatch.setattr(window._update_pool, "start", started.append)
    window.automatic_updates_action.setChecked(False)
    window.start_automatic_update_check()
    assert not started
    assert window.settings.value("updates/enabled") is False
    window.check_for_updates()
    assert len(started) == 1
    window._update_task = None
    window.automatic_updates_action.setChecked(True)
    window.start_automatic_update_check()
    assert len(started) == 1
    window.settings.setValue("updates/last_check_epoch", int(time.time()) + 90000)
    window.start_automatic_update_check()
    assert len(started) == 2
    window._update_task = None


@pytest.mark.parametrize("manual", [False, True])
def test_offline_worker_delivers_on_gui_thread(update_window, monkeypatch, manual):
    from PySide6.QtCore import QThread
    from openpdf_editor import version_check as module
    from openpdf_editor.main_window import QMessageBox
    app, window = update_window
    messages = []
    def offline(*args): raise OSError("offline")
    monkeypatch.setattr(module, "fetch_latest_release", offline)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(QThread.currentThread()))
    window._start_update_check(manual=manual)
    deadline = time.monotonic() + 5
    while window._update_task is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert window._update_task is None
    assert messages == ([app.thread()] if manual else [])


def test_new_release_opens_only_after_user_confirmation(update_window, monkeypatch):
    from openpdf_editor import main_window as module
    _, window = update_window
    opened = []
    monkeypatch.setattr(module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    monkeypatch.setattr(module.QMessageBox, "exec", lambda self: 0)
    release = ReleaseInfo("99.0.0", "https://github.com/pusmartinczech-ship-it/Nettongia/releases/tag/v99.0.0")
    window._update_manual = True
    window._update_check_finished(release)
    assert not opened
    monkeypatch.setattr(module.QMessageBox, "clickedButton", lambda self: self.buttons()[0])
    window._update_check_finished(release)
    assert opened == [release.page_url]


def test_closed_window_ignores_late_result(update_window, monkeypatch):
    from openpdf_editor.main_window import QMessageBox
    _, window = update_window
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: calls.append(args))
    window._update_manual = True
    window.close()
    window._update_check_failed()
    window._update_check_finished(ReleaseInfo("99.0.0", "https://github.com/"))
    assert not calls


def test_current_version_is_silent_unless_requested(update_window, monkeypatch):
    from openpdf_editor import __version__
    from openpdf_editor.main_window import QMessageBox
    _, window = update_window
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: calls.append(args))
    release = ReleaseInfo(__version__, "https://github.com/")
    window._update_check_finished(release)
    assert not calls
    window._update_manual = True
    window._update_check_finished(release)
    assert len(calls) == 1


def test_notification_is_not_repeated_and_disable_suppresses_pending_result(update_window, monkeypatch):
    from openpdf_editor.main_window import QMessageBox
    _, window = update_window
    calls = []
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: calls.append(1))
    release = ReleaseInfo("99.0.0", "https://github.com/")
    window._update_check_finished(release)
    window._update_check_finished(release)
    assert len(calls) == 1
    window.automatic_updates_action.setChecked(False)
    window._update_check_finished(ReleaseInfo("100.0.0", "https://github.com/"))
    assert len(calls) == 1
