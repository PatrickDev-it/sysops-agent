"""
Web search tool — no API key required.

Backend: ddgs (DuckDuckGo Search) — pip install ddgs, no API key required.

Returns a ranked list of results as plain text for the supervisor (4B) to reason on.
"""

import re as _re
from datetime import datetime
from pathlib import Path

# OS/shell/jargon tokens a model over-adds to queries. Stripping them yields the
# LATEST GENERAL method (better results) instead of a narrow, brittle search.
_QUERY_NOISE_WORDS = frozenset(
    {
        "windows",
        "powershell",
        "pwsh",
        "linux",
        "macos",
        "darwin",
        "bash",
        "cmd",
        "zsh",
        "ubuntu",
        "debian",
        "win32",
        "win",
        "non-interactive",
        "noninteractive",
    }
)


def _simplify_query(query: str) -> str:
    """Strip over-specification the model adds: quotes, pinned versions, OS/shell
    names, jargon. A short natural query ("<tech> latest init cli") returns far
    better results than a narrow one — you want the CURRENT general method, not a
    pinned version on one OS. Deterministic; single owner of query hygiene.
    """
    q = (query or "").replace('"', " ").replace("'", " ")
    q = _re.sub(r"@\S+", " ", q)  # @16.2.6 / @latest pins
    q = _re.sub(r"\bv?\d+(?:\.\d+)+\b", " ", q)  # 16.2.6, v22.13.0
    q = _re.sub(r"\b\d{1,3}\+?\b", " ", q)  # standalone 15 / 15+ version tokens
    words = [w for w in q.split() if w.lower() not in _QUERY_NOISE_WORDS]
    return _re.sub(r"\s{2,}", " ", " ".join(words)).strip(" -")


def _correct_temporal(query: str) -> str:
    """Force the query's temporal frame to the REAL current year.

    The model authors queries with a year frozen at its training era (e.g.
    "2025"). The runtime knows the true date, so it strips any model-injected
    4-digit year and appends the actual current year. This is what lets an
    out-of-date model search for TODAY's conventions instead of its own era.
    Deterministic, single owner of query temporal hygiene.
    """
    year = datetime.now().year
    q = _re.sub(r"\b(?:19|20)\d{2}\b", "", query)  # drop any stale year token
    q = _re.sub(r"\s{2,}", " ", q).strip(" -")
    if str(year) not in q:
        q = f"{q} {year}".strip()
    return q


def search(query: str, cwd: "Path | None" = None, max_results: int = 6) -> tuple[bool, str]:
    """
    Search the web using DuckDuckGo. No API key needed.
    Returns (ok, results_text).
    """
    query = _correct_temporal(_simplify_query((query or "").strip()))
    if not query:
        return False, "web_search: empty query"

    # Primary: ddgs library (most reliable, handles bot detection internally)
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
        if hits:
            lines = [f"SEARCH: {query}"]
            for i, r in enumerate(hits, 1):
                title = r.get("title", "").strip()
                # Longer snippet: the 200-char cut usually dropped the actual
                # command/flags. 500 chars keeps enough to be actionable for the
                # step that consumes this research.
                body = r.get("body", "").strip()[:500]
                url = r.get("href", "").strip()
                lines.append(f"[{i}] {title}")
                if body:
                    lines.append(f"    {body}")
                if url:
                    lines.append(f"    {url}")
            return True, "\n".join(lines)
    except ImportError:
        return False, "web_search: ddgs not installed. Run: pip install ddgs"
    except Exception as exc:
        return False, f"web_search (ddgs) failed: {exc}"
    return False, f"web_search: no results for {query!r}"
