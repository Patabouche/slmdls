# SlimeDeals — masquage des informations sensibles dans les journaux / UI logs.
from __future__ import annotations

import re

# Jetons catalogue (préfixe historique)
_RE_TTC_TOKEN = re.compile(r"\bttc_[A-Za-z0-9_]{8,}\b", re.IGNORECASE)
_RE_AUTH_QS = re.compile(r"auth_token=[A-Za-z0-9_]+", re.IGNORECASE)


def redact_sensitive_log_text(text: str) -> str:
    """Retire ou remplace domaines, jetons et URLs sensibles (logs utilisateur / fichier)."""
    if not text or not isinstance(text, str):
        return text if isinstance(text, str) else ""
    s = text
    for needle in (
        "api.twentytwocloud.com",
        "twentytwocloud",
        "TwentyTwoCloud",
        "slimedeals.fr",
        "SLIMEDEALS_API",
        "SLIMEDEALS_CATALOG",
        "CATALOG_API",
        "CATALOG_TOKEN",
    ):
        s = s.replace(needle, "[api]")
        s = s.replace(needle.lower(), "[api]")
        s = s.replace(needle.upper(), "[api]")
    s = _RE_AUTH_QS.sub("auth_token=[redacted]", s)
    s = _RE_TTC_TOKEN.sub("[token]", s)
    return s
