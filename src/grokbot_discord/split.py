DISCORD_CHUNK = 1900  # Discord hard limit is 2000; leave headroom


def _cut_point(text: str, limit: int) -> int:
    window = text[:limit]
    cut = window.rfind("\n\n")
    if cut > limit // 4:
        return cut
    for sep in ("\n", " "):
        cut = window.rfind(sep)
        if cut > 0:
            return cut
    return limit


def split_message(text: str, limit: int = DISCORD_CHUNK) -> list[str]:
    """Split on paragraph, then line, then word boundaries; hard-cut as a last resort."""
    text = (text or "").strip()
    if not text:
        return []
    parts: list[str] = []
    while len(text) > limit:
        cut = _cut_point(text, limit)
        head = text[:cut].rstrip()
        if head:
            parts.append(head)
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts
