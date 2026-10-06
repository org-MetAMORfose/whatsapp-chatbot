"""Conversation-history representation for approved WhatsApp templates."""


def template_history_content(
    name: str,
    language: str,
    parameters: tuple[str, ...],
) -> str:
    """Preserve template identity and values when its approved body is unavailable."""
    return f"[template:{name}:{language}] " + " | ".join(parameters)
