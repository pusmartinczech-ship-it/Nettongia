#!/usr/bin/env python3
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HTML_FILES = sorted(ROOT.glob("*.html"))
REQUIRED_POLICY = (
    "Code signing policy",
    "Free code signing provided by",
    "SignPath.io",
    "SignPath Foundation",
    "This program will not transfer any information",
)
APPROVED_SUPPORT_URL = "https://buy.stripe.com/dRm00ca0yeYK1am9ix7ss00"

class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.inline_scripts = 0
        self.inline_styles = 0
        self.titles = 0
        self.headings = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            if not values.get("src"):
                self.inline_scripts += 1
            elif values["src"]:
                self.links.append(("script", values["src"]))
        elif tag == "style":
            self.inline_styles += 1
        elif tag in {"a", "link"} and values.get("href"):
            self.links.append((tag, values["href"] or ""))
        elif tag in {"img", "source"} and values.get("src"):
            self.links.append((tag, values["src"] or ""))
        elif tag == "title":
            self.titles += 1
        elif tag == "h1":
            self.headings += 1

def local_target(page: Path, value: str) -> Path | None:
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith(("#", "mailto:", "tel:")):
        return None
    path = parsed.path
    if not path:
        return None
    if path.startswith("/"):
        target = ROOT / path.lstrip("/")
    else:
        target = page.parent / path
    if target.is_dir() or path.endswith("/"):
        target /= "index.html"
    return target.resolve()

def main() -> int:
    errors: list[str] = []
    if not HTML_FILES:
        errors.append("No HTML files found")
    for page in HTML_FILES:
        parser = PageParser()
        source = page.read_text(encoding="utf-8")
        parser.feed(source)
        if parser.titles != 1:
            errors.append(f"{page.name}: expected exactly one title")
        if parser.headings != 1:
            errors.append(f"{page.name}: expected exactly one h1")
        if parser.inline_scripts or parser.inline_styles:
            errors.append(f"{page.name}: inline script/style violates CSP")
        for tag, value in parser.links:
            target = local_target(page, value)
            if target is not None and not target.exists():
                errors.append(f"{page.name}: broken local {tag} target {value}")
    policy = (ROOT / "code-signing-policy.html").read_text(encoding="utf-8")
    for phrase in REQUIRED_POLICY:
        if phrase not in policy:
            errors.append(f"Signing policy missing: {phrase}")
    headers = (ROOT / "_headers").read_text(encoding="utf-8")
    for header in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy"):
        if header not in headers:
            errors.append(f"Missing security header: {header}")
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    if len(re.findall(r"\b[a-f0-9]{64}\b", index, flags=re.I)) != 1:
        errors.append("Download section must publish exactly one portable ZIP SHA-256")
    if index.count("data-download") != 1 or "-portable.zip" not in index:
        errors.append("Homepage must offer exactly one portable-version download")
    if "Installer SHA-256" in index or "-x64.exe" in index:
        errors.append("Homepage must not offer an installer download")
    if re.search(r"<(?:script|img|link)[^>]+(?:src|href)=[\"']https?://", index, flags=re.I):
        errors.append("Homepage loads an external executable asset")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    counters = ROOT / "functions" / "api" / "counters.js"
    if 'setLanguage(stored || "en")' not in app:
        errors.append("English must remain the default website language")
    if "@media(prefers-color-scheme:dark)" not in styles:
        errors.append("Website must follow the operating-system dark theme")
    for token in (
        "color-scheme:light dark",
        ".secondary{color:var(--teal)}",
        ".language button[aria-pressed=true]{color:#061315}",
        ".privacy-grid a{color:var(--teal)}",
    ):
        if token not in styles:
            errors.append(f"Theme contrast or system preference rule is missing: {token}")
    for page in HTML_FILES:
        if 'name="color-scheme" content="light dark"' not in page.read_text(encoding="utf-8"):
            errors.append(f"{page.name}: system color-scheme metadata is missing")
    if index.count("mailto:support@nettongia.com") < 2:
        errors.append("Support email must be visible in the homepage content and footer")
    if index.count(APPROVED_SUPPORT_URL) != 1:
        errors.append("Homepage must publish exactly the approved Stripe support link")
    stripe_links = re.findall(r"https://buy\\.stripe\\.com/[A-Za-z0-9_]+", index)
    if stripe_links != [APPROVED_SUPPORT_URL]:
        errors.append("Homepage contains an unapproved Stripe payment link")
    if any(token in index for token in ("stripe-buy-button", "js.stripe.com", "pk_test_", "buy.stripe.com/test_")):
        errors.append("Homepage must not embed Stripe scripts or test credentials")
    for phrase in ("User feedback", "improvement ideas", "GitHub Issues"):
        if phrase not in index:
            errors.append(f"Feedback invitation is missing: {phrase}")
    if not counters.exists() or "env.COUNTERS" not in counters.read_text(encoding="utf-8"):
        errors.append("Cloudflare aggregate counter endpoint is missing")
    if "connect-src 'self'" not in headers:
        errors.append("CSP must permit same-origin counter requests")
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print(f"Website check passed: {len(HTML_FILES)} HTML pages, local assets and policies valid.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
