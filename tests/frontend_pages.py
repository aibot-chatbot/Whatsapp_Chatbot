"""Where a page's source lives while pages move from frontend/ to Astro one at a time."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
WEB_PAGES = ROOT / "web" / "src" / "pages"
# Former inline scripts of migrated pages, moved verbatim; Astro copies web/public into the build.
WEB_PUBLIC_JS = ROOT / "web" / "public" / "assets" / "js"


def page_source_path(name):
    """web/src/pages/<stem>.astro once Astro builds the page at /<name>, else frontend/<name>."""
    # Pages are flat "x.html" names; a folder or another suffix would silently match the top-level page.
    if Path(name).name != name or Path(name).suffix != ".html":
        raise ValueError(f"expected a top-level page name like 'bots.html', got {name!r}")
    migrated = WEB_PAGES / f"{Path(name).stem}.astro"
    return migrated if migrated.is_file() else FRONTEND / name
