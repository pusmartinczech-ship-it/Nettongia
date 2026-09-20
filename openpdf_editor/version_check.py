"""Small, privacy-preserving GitHub release checker.

The checker sends only a normal GitHub API request. It never sends the open
document, its name, its path, or any diagnostic data. Network failures are
deliberately treated as a normal offline state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QRunnable, Signal


CURRENT_RELEASE_API = "https://api.github.com/repos/pusmartinczech-ship-it/Nettongia/releases?per_page=20"
DEFAULT_RELEASE_PAGE = "https://github.com/pusmartinczech-ship-it/Nettongia/releases"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$", re.IGNORECASE)
MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    page_url: str
    portable_asset_url: str | None = None


def version_tuple(value: str) -> tuple[int, int, int]:
    """Return a comparable semantic version tuple or raise ValueError."""

    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Unsupported release version: {value!r}")
    return tuple(int(part or 0) for part in match.groups())


def is_newer(current: str, candidate: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def _parse_release_data(data: object) -> ReleaseInfo:
    if not isinstance(data, dict):
        raise ValueError("GitHub release response is not an object")
    if data.get("draft"):
        raise ValueError("Draft releases are not published")
    tag = data.get("tag_name")
    if not isinstance(tag, str):
        raise ValueError("GitHub release has no valid tag")
    version_tuple(tag)
    page_url = data.get("html_url")
    if not isinstance(page_url, str) or not page_url.startswith(DEFAULT_RELEASE_PAGE + "/tag/"):
        page_url = DEFAULT_RELEASE_PAGE
    asset_url: str | None = None
    assets = data.get("assets", [])
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).lower()
            url = asset.get("browser_download_url")
            if ("portable" in name and name.endswith(".zip")
                    and isinstance(url, str) and url.startswith(DEFAULT_RELEASE_PAGE + "/download/")):
                asset_url = url
                break
    return ReleaseInfo(tag.lstrip("vV"), page_url, asset_url)


def parse_release(payload: str) -> ReleaseInfo:
    """Parse one published release, including an official public beta."""

    return _parse_release_data(json.loads(payload))


def parse_release_feed(payload: str) -> ReleaseInfo:
    """Return the newest valid published release from a GitHub release feed."""

    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("GitHub release response is not a list")
    candidates: list[ReleaseInfo] = []
    for item in data:
        try:
            candidates.append(_parse_release_data(item))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("GitHub release feed has no valid published release")
    return max(candidates, key=lambda release: version_tuple(release.version))


def fetch_latest_release(timeout: float = 4.0) -> ReleaseInfo:
    request = Request(
        CURRENT_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Nettongia-PDF-Editor-version-check",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("Release metadata exceeds size limit")
        return parse_release_feed(payload.decode("utf-8"))


class VersionCheckSignals(QObject):
    finished = Signal(object)
    failed = Signal()


class VersionCheckTask(QRunnable):
    """Run the release query away from the GUI thread."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = VersionCheckSignals()

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        try:
            self.signals.finished.emit(fetch_latest_release())
        except Exception:
            # An offline computer, a proxy, rate limiting, or a temporary GitHub
            # error must never affect opening or editing a local PDF.
            self.signals.failed.emit()
