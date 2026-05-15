# SlimeDeals — classification des rangs launcher (FREE / Monstre / Triple Monstre)
# Source unique alignée avec le bot / API ; le serveur envoie des chaînes normalisées.

from __future__ import annotations

from typing import Literal

LauncherRankBucket = Literal["free", "monstre", "pass24h", "triple"]

# Limite de jeux distincts (install via le launcher) pour le palier Monstre.
MONSTRE_MAX_DISTINCT_INSTALLS = 10
# Palier 24HPASS : 8 jeux distincts au choix (hors reinstall d'un deja enregistre).
PASS24H_MAX_DISTINCT_INSTALLS = 8


def norm_launcher_rank(rank) -> str:
    if rank is None:
        return "free"
    r = str(rank).strip().lower().replace(" ", "_")
    if not r or r in ("none", "null"):
        return "free"
    return r


# Rangs « Triple Monstre » (aligné bot / store historique)
TRIPLE_RANK_IDS = frozenset(
    {
        "triple_monstre",
        "triplemonstre",
        "triple_monster",
        "triplemonster",
        "triple",
        "tm",
        "unlimited",
        "role_unlimited",
        "vip",
        "premium",
    }
)

# Rangs « Monstre » (palier intermédiaire — à renseigner côté serveur Discord / API)
MONSTRE_RANK_IDS = frozenset(
    {
        "monstre",
        "monster",
        "plan_monstre",
        "role_monstre",
        "double_monstre",
        "deux_monstres",
        "pass_monstre",
    }
)

# Pass 24 h — aligner les chaînes renvoyées par l'API / le bot Discord.
PASS24H_RANK_IDS = frozenset(
    {
        "24hpass",
        "24h_pass",
        "pass_24h",
        "pass24h",
        "hpass24",
        "day_pass_24h",
        "pass_24hpass",
    }
)


def launcher_rank_bucket(rank) -> LauncherRankBucket:
    """
    Regroupe le rang serveur en paliers affichés dans le launcher.
    Tout rang payant non reconnu (Triple / 24HPASS / Monstre explicite) est traité comme Monstre.
    """
    r = norm_launcher_rank(rank)
    if r == "free":
        return "free"
    if r in TRIPLE_RANK_IDS:
        return "triple"
    if r in PASS24H_RANK_IDS:
        return "pass24h"
    if r in MONSTRE_RANK_IDS:
        return "monstre"
    return "monstre"


def paid_install_slot_cap_for_bucket(bucket: LauncherRankBucket) -> int | None:
    """Nombre max de jeux distincts via le launcher, ou None = illimite (Triple)."""
    if bucket == "monstre":
        return MONSTRE_MAX_DISTINCT_INSTALLS
    if bucket == "pass24h":
        return PASS24H_MAX_DISTINCT_INSTALLS
    if bucket == "triple":
        return None
    return None


def triple_exclusive_tools_allowed_for_rank(rank) -> bool:
    """Online FIX (multiplayer) et ROCKSTAR BYPASS : reserves au Triple Monstre uniquement."""
    return launcher_rank_bucket(rank) == "triple"


def is_paid_launcher_rank(rank) -> bool:
    """True si le compte n'est pas FREE (Monstre ou Triple ou autre rang payant)."""
    return norm_launcher_rank(rank) != "free"


def cloud_saves_launcher_allowed_for_rank(rank) -> bool:
    """Sauvegardes cloud (Drive / rclone) : uniquement Triple Monstre."""
    return launcher_rank_bucket(rank) == "triple"
