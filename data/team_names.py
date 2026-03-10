"""
Team Name Mapping

Team names differ across APIs. This module maps between:
- football-data.org names
- Odds API names
- API-Football names

Expand this as you encounter mismatches.
"""

# Format: canonical_name -> {api: name_used_by_that_api}
TEAM_MAP = {
    # === Premier League ===
    "Arsenal": {
        "football_data": "Arsenal FC",
        "odds_api": "Arsenal",
        "api_football": "Arsenal",
    },
    "Aston Villa": {
        "football_data": "Aston Villa FC",
        "odds_api": "Aston Villa",
        "api_football": "Aston Villa",
    },
    "Bournemouth": {
        "football_data": "AFC Bournemouth",
        "odds_api": "Bournemouth",
        "api_football": "Bournemouth",
    },
    "Brentford": {
        "football_data": "Brentford FC",
        "odds_api": "Brentford",
        "api_football": "Brentford",
    },
    "Brighton": {
        "football_data": "Brighton & Hove Albion FC",
        "odds_api": "Brighton and Hove Albion",
        "api_football": "Brighton",
    },
    "Chelsea": {
        "football_data": "Chelsea FC",
        "odds_api": "Chelsea",
        "api_football": "Chelsea",
    },
    "Crystal Palace": {
        "football_data": "Crystal Palace FC",
        "odds_api": "Crystal Palace",
        "api_football": "Crystal Palace",
    },
    "Everton": {
        "football_data": "Everton FC",
        "odds_api": "Everton",
        "api_football": "Everton",
    },
    "Fulham": {
        "football_data": "Fulham FC",
        "odds_api": "Fulham",
        "api_football": "Fulham",
    },
    "Liverpool": {
        "football_data": "Liverpool FC",
        "odds_api": "Liverpool",
        "api_football": "Liverpool",
    },
    "Manchester City": {
        "football_data": "Manchester City FC",
        "odds_api": "Manchester City",
        "api_football": "Manchester City",
    },
    "Manchester United": {
        "football_data": "Manchester United FC",
        "odds_api": "Manchester United",
        "api_football": "Manchester Utd",
    },
    "Newcastle": {
        "football_data": "Newcastle United FC",
        "odds_api": "Newcastle United",
        "api_football": "Newcastle",
    },
    "Nottingham Forest": {
        "football_data": "Nottingham Forest FC",
        "odds_api": "Nottingham Forest",
        "api_football": "Nottingham Forest",
    },
    "Tottenham": {
        "football_data": "Tottenham Hotspur FC",
        "odds_api": "Tottenham Hotspur",
        "api_football": "Tottenham",
    },
    "West Ham": {
        "football_data": "West Ham United FC",
        "odds_api": "West Ham United",
        "api_football": "West Ham",
    },
    "Wolverhampton": {
        "football_data": "Wolverhampton Wanderers FC",
        "odds_api": "Wolverhampton Wanderers",
        "api_football": "Wolves",
    },
    # === La Liga ===
    "Barcelona": {
        "football_data": "FC Barcelona",
        "odds_api": "Barcelona",
        "api_football": "Barcelona",
    },
    "Real Madrid": {
        "football_data": "Real Madrid CF",
        "odds_api": "Real Madrid",
        "api_football": "Real Madrid",
    },
    "Atletico Madrid": {
        "football_data": "Club Atlético de Madrid",
        "odds_api": "Atletico Madrid",
        "api_football": "Atletico Madrid",
    },
    "Real Sociedad": {
        "football_data": "Real Sociedad de Fútbol",
        "odds_api": "Real Sociedad",
        "api_football": "Real Sociedad",
    },
    "Real Betis": {
        "football_data": "Real Betis Balompié",
        "odds_api": "Real Betis",
        "api_football": "Real Betis",
    },
    "Villarreal": {
        "football_data": "Villarreal CF",
        "odds_api": "Villarreal",
        "api_football": "Villarreal",
    },
    "Athletic Bilbao": {
        "football_data": "Athletic Club",
        "odds_api": "Athletic Bilbao",
        "api_football": "Athletic Club",
    },
    "Sevilla": {
        "football_data": "Sevilla FC",
        "odds_api": "Sevilla",
        "api_football": "Sevilla",
    },
    # === Bundesliga ===
    "Bayern Munich": {
        "football_data": "FC Bayern München",
        "odds_api": "Bayern Munich",
        "api_football": "Bayern Munich",
    },
    "Borussia Dortmund": {
        "football_data": "Borussia Dortmund",
        "odds_api": "Borussia Dortmund",
        "api_football": "Borussia Dortmund",
    },
    "RB Leipzig": {
        "football_data": "RB Leipzig",
        "odds_api": "RB Leipzig",
        "api_football": "RB Leipzig",
    },
    "Bayer Leverkusen": {
        "football_data": "Bayer 04 Leverkusen",
        "odds_api": "Bayer Leverkusen",
        "api_football": "Bayer Leverkusen",
    },
    "Eintracht Frankfurt": {
        "football_data": "Eintracht Frankfurt",
        "odds_api": "Eintracht Frankfurt",
        "api_football": "Eintracht Frankfurt",
    },
}


def _build_reverse_index():
    """Build a reverse lookup: (api_name, source) -> canonical_name"""
    index = {}
    for canonical, apis in TEAM_MAP.items():
        for source, name in apis.items():
            index[(name.lower(), source)] = canonical
            # Also index without source for fuzzy matching
            index[(name.lower(), "any")] = canonical
    return index


_REVERSE_INDEX = _build_reverse_index()


def normalize_team_name(name: str, source: str = "any") -> str:
    """
    Convert any API-specific team name to our canonical name.
    Falls back to the original name if no mapping found.
    """
    key = (name.lower(), source)
    if key in _REVERSE_INDEX:
        return _REVERSE_INDEX[key]

    # Try without source
    key_any = (name.lower(), "any")
    if key_any in _REVERSE_INDEX:
        return _REVERSE_INDEX[key_any]

    # Try partial match
    name_clean = name.lower().replace("fc", "").replace("cf", "").strip()
    for (mapped_name, _), canonical in _REVERSE_INDEX.items():
        if name_clean in mapped_name or mapped_name in name_clean:
            return canonical

    return name  # Return original if no match


def get_api_name(canonical: str, target_api: str) -> str:
    """Convert canonical name to API-specific name."""
    if canonical in TEAM_MAP:
        return TEAM_MAP[canonical].get(target_api, canonical)
    return canonical
