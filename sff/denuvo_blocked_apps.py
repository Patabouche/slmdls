"""
Jeux protégés Denuvo — téléchargement classique (onglet Télécharger) interdit.
Disponibles ou à venir via Jeux VIP (Triple Monstre).
"""
from __future__ import annotations

import json

# app_id → nom affiché
DENUVO_BLOCKED_GAMES: dict[str, str] = {
    "3274580": "Anno 117: Pax Romana",
    "3159330": "Assassin's Creed Shadows",
    "3751950": "Assassin's Creed Black Flag Resynced",
    "801800": "Atomfall",
    "2840770": "Avatar: Frontiers of Pandora",
    "2556990": "Beyond Good & Evil - 20th Anniversary Edition",
    "671860": "BattleBit Remastered",
    "2833580": "BRAVELY DEFAULT FLYING FAIRY HD Remaster",
    "1285190": "Borderlands 4",
    "2604480": "City Transport Simulator®",
    "1295660": "Sid Meier's Civilization VII",
    "2362060": "CODE VEIN II",
    "1677280": "Company of Heroes 3",
    "1273400": "Construction Simulator",
    "3321460": "Crimson Desert",
    "1490890": "Demon Slayer: Kimetsu no Yaiba - The Hinokami Chronicles",
    "2928600": "Demon Slayer: Kimetsu no Yaiba - The Hinokami Chronicles 2",
    "2424110": "Demon Slayer -Kimetsu no Yaiba- Sweep the Board!",
    "1984270": "Digimon Story Time Stranger",
    "1038250": "DIRT 5",
    "2499860": "DRAGON QUEST VII Reimagined",
    "1172710": "Dune: Awakening",
    "2195250": "EA SPORTS FC 24",
    "2669320": "EA SPORTS FC 25",
    "3405690": "EA SPORTS FC 26",
    "1849250": "EA SPORTS WRC",
    "408250": "Eagle Flight",
    "1868180": "Etrian Odyssey HD",
    "1868170": "Etrian Odyssey II HD",
    "1810820": "Etrian Odyssey III HD",
    "700600": "Evil Genius 2: World Domination",
    "2108330": "F1® 23",
    "2488620": "F1® 24",
    "3059520": "F1® 25",
    "2591280": "F1 Manager 2024",
    "1225580": "Fe",
    "1004640": "FINAL FANTASY TACTICS - The Ivalice Chronicles",
    "420560": "Firefighting Simulator - The Squad",
    "3551340": "Football Manager 26",
    "304390": "FOR HONOR",
    "3094260": "FortiFyte",
    "1307710": "GRID Legends",
    "2878600": "Harry Potter: Quidditch Champions",
    "1761390": "Hatsune Miku: Project DIVA Mega Mix+",
    "2495100": "Hello Kitty Island Adventure",
    "2958130": "Jurassic World Evolution 3",
    "2375550": "Like a Dragon: Gaiden",
    "2072450": "Like a Dragon: Infinite Wealth",
    "1805480": "Like a Dragon: Ishin",
    "3061810": "Like a Dragon: Pirate Yakuza in Hawaii",
    "1462570": "Lost in Random™",
    "2058190": "Lost Judgment",
    "2624870": "Life is Strange: Reunion",
    "2215200": "LEGO® Batman™: Legacy of the Dark Knight",
    "2582560": "EA SPORTS Madden NFL 25",
    "3230400": "EA SPORTS Madden NFL 26",
    "1941540": "Mafia: The Old Country",
    "3065800": "Marathon",
    "2403100": "Marvel's Midnight Suns",
    "2246340": "Monster Hunter Wilds",
    "2852190": "Monster Hunter Stories 3: Twisted Reflection",
    "976310": "Mortal Kombat 1",
    "2878980": "NBA 2K25",
    "3472040": "NBA 2K26",
    "1846380": "Need for Speed Unbound",
    "3014320": "OCTOPATH TRAVELER 0",
    "3046600": "Onimusha 2: Samurai's Destiny",
    "2161700": "Persona 3 Reload",
    "1809740": "Persona 3 Portable",
    "1602010": "Persona 4 Arena Ultimax",
    "4115450": "Phantom Blade Zero",
    "2385530": "PGA TOUR 2K25",
    "2688950": "Planet Coaster 2",
    "421020": "Plants vs. Zombies: Garden Warfare 2",
    "221410": "Rocksmith 2014 Edition - Remastered",
    "2288350": "RAIDOU Remastered: The Mystery of the Soulless Army",
    "2169200": "Sniper Elite Resistance",
    "1794960": "Sonic Origins",
    "2022670": "Sonic Superstars",
    "2486820": "Sonic Racing: CrossWorlds",
    "2513280": "SONIC X SHADOW GENERATIONS",
    "2114740": "Soul Hackers 2",
    "2842040": "Star Wars Outlaws",
    "1364780": "Street Fighter 6",
    "4260840": "STRANGER THAN HEAVEN",
    "4078430": "STAR WARS: Galactic Racer™",
    "2680010": "The First Berserker: Khazan",
    "1142710": "Total War: WARHAMMER III",
    "2185060": "Two Point Museum",
    "2741360": "Valiant Hearts: Coming Home",
    "3717070": "WWE 2K26",
    "3937550": "Yakuza Kiwami 3 & Dark Ties",
    "2058030": "Zombie Army VR",
    "2361770": "SHINOBI: Art of Vengeance",
    "1029690": "Sniper Elite 5",
    "2051010": "Professional Baseball Spirits 2024-2025",
    # Titres listés sans URL explicite (pages Steam actives connues)
    "879177": "Suicide Squad: Kill the Justice League",
    "1214080": "Prince of Persia: The Lost Crown",
    "1294810": "Redfall",
    "1460560": "The Settlers: New Allies",
    "2231380": "Tom Clancy's Ghost Recon Breakpoint",
    "2254740": "Persona 5 Tactica",
    "2338770": "NBA 2K24",
    "1222730": "STAR WARS: Squadrons",
    "1611910": "Warhammer 40,000: Chaos Gate - Daemonhunters",
    "1844380": "Warhammer Age of Sigmar: Realms of Ruin",
    "694280": "Zombie Army 4: Dead War",
    "1785650": "TopSpin 2K25",
    "976590": "The Bus",
    "1451190": "Undisputed",
    "1482060": "Super Mega Baseball 4",
    "641080": "Trials Rising",
    "321960": "Might & Magic: Heroes VII",
}

DENUVO_BLOCKED_IDS: frozenset[str] = frozenset(DENUVO_BLOCKED_GAMES.keys())

DENUVO_BLOCK_MESSAGE = (
    "Ce jeu n'est pas disponible au téléchargement ici car il est protégé par Denuvo. "
    "Il peut être disponible dans Jeux VIP (Triple Monstre), ou sera ajouté prochainement — "
    "tu peux faire une demande sur Discord."
)


def normalize_app_id(app_id: str | int | None) -> str:
    return str(app_id or "").strip()


def denuvo_blocked_info(app_id: str | int | None) -> dict | None:
    aid = normalize_app_id(app_id)
    if not aid or aid not in DENUVO_BLOCKED_IDS:
        return None
    return {
        "app_id": aid,
        "name": DENUVO_BLOCKED_GAMES.get(aid, f"App {aid}"),
        "message": DENUVO_BLOCK_MESSAGE,
    }


def is_denuvo_blocked(app_id: str | int | None) -> bool:
    return denuvo_blocked_info(app_id) is not None


def blocked_apps_json() -> str:
    return json.dumps({"apps": DENUVO_BLOCKED_GAMES}, ensure_ascii=False)
