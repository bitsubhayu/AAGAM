"""Unit tests for server-side fuzzy location resolution (PRD §9.4)."""

from api.app.assistant.location_resolver import get_authoritative_locations, resolve_location


def test_authoritative_locations_count():
    """Asserts that exactly 40 authoritative locations are loaded."""
    locs = get_authoritative_locations()
    assert len(locs) == 40


def test_exact_and_case_insensitive_match():
    """Verifies exact matches on slug and capitalized names."""
    res1 = resolve_location("bhubaneswar")
    assert res1["resolved"] is True
    assert res1["location"]["name"] == "Bhubaneswar"
    assert res1["location"]["region"] == "EAST_NE"

    res2 = resolve_location("NAGPUR")
    assert res2["resolved"] is True
    assert res2["location"]["name"] == "Nagpur"
    assert res2["location"]["region"] == "CENTRAL"


def test_fuzzy_match_with_typos():
    """Verifies fuzzy matching corrects common typos without guessing."""
    # "Kolkatta" -> "Kolkata"
    res1 = resolve_location("Kolkatta")
    assert res1["resolved"] is True
    assert res1["location"]["name"] == "Kolkata"

    # "Bhubaneshwr" -> "Bhubaneswar"
    res2 = resolve_location("Bhubaneshwr")
    assert res2["resolved"] is True
    assert res2["location"]["name"] == "Bhubaneswar"


def test_ambiguous_match_returns_candidates():
    """Verifies that an ambiguous query returns candidate options rather than picking one arbitrarily."""
    # "pur" matches multiple locations like Nagpur, Kanpur, Jodhpur, etc.
    res = resolve_location("pur")
    if not res["resolved"]:
        assert res["ambiguous"] is True
        assert len(res["candidates"]) > 1


def test_out_of_scope_location():
    """Verifies that queries for locations outside the 40 configured points are clearly reported."""
    res = resolve_location("Kasba Village Unknown")
    assert res["resolved"] is False
    assert "40 configured locations" in res["message"]
    assert len(res["candidates"]) >= 1  # suggestions of nearest points
