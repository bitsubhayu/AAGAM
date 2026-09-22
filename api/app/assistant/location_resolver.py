"""Server-side fuzzy location resolver for the 40 authoritative AAGAM locations (PRD §9.4).

Resolves user-supplied location strings strictly against the 40 locations:
- Exact/clear match -> resolves to canonical location
- Ambiguous match -> returns candidates rather than guessing
- No match -> clearly reports unavailable location and suggests nearest/regional stations
- Never invents a location or silently picks an ambiguous candidate.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any, Dict, List, Optional

from core.config import get_locations

logger = logging.getLogger("aagam.assistant.location_resolver")

_LOCATIONS_CACHE: Optional[List[Dict[str, Any]]] = None


def get_authoritative_locations() -> List[Dict[str, Any]]:
    """Returns the 40 authoritative location definitions."""
    global _LOCATIONS_CACHE
    if _LOCATIONS_CACHE is None:
        locs = get_locations()
        # Ensure id is assigned
        for idx, loc in enumerate(locs):
            if "id" not in loc:
                loc["id"] = idx + 1
        _LOCATIONS_CACHE = locs
    return _LOCATIONS_CACHE


def resolve_location(query: str) -> Dict[str, Any]:
    """Resolves a user-supplied location query against the 40 authoritative locations.

    Returns a dict with:
    - resolved: bool
    - location: Optional[Dict[str, Any]]
    - ambiguous: bool
    - candidates: List[str]
    - message: Optional[str]
    """
    if not query or not query.strip():
        return {
            "resolved": False,
            "location": None,
            "ambiguous": False,
            "candidates": [],
            "message": "No location specified.",
        }

    q_clean = query.strip().lower()
    locations = get_authoritative_locations()

    # 1. Exact match check (name or slug)
    for loc in locations:
        if loc["slug"].lower() == q_clean or loc["name"].lower() == q_clean:
            return {
                "resolved": True,
                "location": loc,
                "ambiguous": False,
                "candidates": [loc["name"]],
                "message": None,
            }

    # 2. Substring match (e.g. "Bhubaneswar district" -> "Bhubaneswar")
    substring_matches = []
    for loc in locations:
        loc_name_lower = loc["name"].lower()
        loc_slug_lower = loc["slug"].lower()
        if loc_name_lower in q_clean or loc_slug_lower in q_clean:
            substring_matches.append(loc)

    if len(substring_matches) == 1:
        return {
            "resolved": True,
            "location": substring_matches[0],
            "ambiguous": False,
            "candidates": [substring_matches[0]["name"]],
            "message": None,
        }
    elif len(substring_matches) > 1:
        return {
            "resolved": False,
            "location": None,
            "ambiguous": True,
            "candidates": [loc["name"] for loc in substring_matches],
            "message": f"Query matches multiple locations: {', '.join(loc['name'] for loc in substring_matches)}.",
        }

    # 3. Fuzzy similarity matching using difflib
    scored: List[tuple[float, Dict[str, Any]]] = []
    for loc in locations:
        score_name = difflib.SequenceMatcher(None, q_clean, loc["name"].lower()).ratio()
        score_slug = difflib.SequenceMatcher(None, q_clean, loc["slug"].lower()).ratio()
        best_score = max(score_name, score_slug)
        scored.append((best_score, loc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_loc = scored[0]
    runner_up_score, runner_up_loc = scored[1] if len(scored) > 1 else (0.0, None)

    # High confidence clear match
    if top_score >= 0.82 and (top_score - runner_up_score >= 0.15 or runner_up_score < 0.60):
        return {
            "resolved": True,
            "location": top_loc,
            "ambiguous": False,
            "candidates": [top_loc["name"]],
            "message": None,
        }

    # Ambiguous match (multiple viable candidates with score >= 0.55)
    candidates = [
        item[1]["name"]
        for item in scored
        if item[0] >= 0.55 and (top_score - item[0] <= 0.18)
    ]
    if len(candidates) > 1:
        return {
            "resolved": False,
            "location": None,
            "ambiguous": True,
            "candidates": candidates[:4],
            "message": f"Ambiguous location '{query}'. Did you mean: {', '.join(candidates[:4])}?",
        }
    elif len(candidates) == 1 and top_score >= 0.65:
        return {
            "resolved": True,
            "location": top_loc,
            "ambiguous": False,
            "candidates": [top_loc["name"]],
            "message": None,
        }

    # No match (< 0.55): Suggest nearest/major regional points
    suggested = [item[1]["name"] for item in scored[:3]]
    return {
        "resolved": False,
        "location": None,
        "ambiguous": False,
        "candidates": suggested,
        "message": f"Location '{query}' is outside AAGAM's 40 configured locations. Nearest configured points: {', '.join(suggested)}.",
    }
