from urllib.parse import urlparse


def normalise(url: str) -> str:
    if not url.startswith(("http://", "https://", "file://", "data:", "about:")):
        return f"https://{url}"
    return url


def looks_like_web_url(raw: str) -> bool:
    url = normalise(raw)
    p = urlparse(url)
    return (
        p.scheme in ("http", "https")
        and bool(p.netloc)  # Explicitly cast to bool
        and ("." in p.netloc or p.netloc.lower() == "localhost")
    )
