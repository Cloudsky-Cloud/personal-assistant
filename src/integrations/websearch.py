import logging

logger = logging.getLogger(__name__)


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via DuckDuckGo. Returns list of {title, url, snippet}."""
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        raw = list(ddgs.text(query, max_results=max_results))
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", ""),
        }
        for r in raw
    ]
    logger.info("Web search %r → %d results", query, len(results))
    return results


def search_news(query: str, max_results: int = 5) -> list[dict]:
    """Search for recent news via DuckDuckGo. Returns list of {title, url, snippet, date, source}."""
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        raw = list(ddgs.news(query, max_results=max_results))
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("body", ""),
            "date": r.get("date", ""),
            "source": r.get("source", ""),
        }
        for r in raw
    ]
    logger.info("News search %r → %d results", query, len(results))
    return results
