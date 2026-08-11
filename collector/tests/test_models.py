import pytest
from pydantic import ValidationError

from collector.models import MatchPayload, Participant, Stats


def participant(i: int, team: int) -> dict:
    return {"puuid": f"puuid-{i}", "riot_id": f"Oyuncu{i}#TR1", "team": team,
            "position": None, "champion": None, "stats": {}}


def payload_dict(**overrides) -> dict:
    base = {
        "source": "lcu_eog",
        "source_game_id": "123",
        "played_at": "2026-08-11T20:41:03Z",
        "duration_s": 1800,
        "winner_team": 100,
        "participants": [participant(i, 100 if i < 5 else 200) for i in range(10)],
    }
    base.update(overrides)
    return base


def test_valid_payload():
    payload = MatchPayload(**payload_dict())
    assert payload.winner_team == 100
    assert len(payload.participants) == 10


def test_not_ten_participants_rejected():
    with pytest.raises(ValidationError, match="10"):
        MatchPayload(**payload_dict(participants=[participant(i, 100) for i in range(5)]))


def test_unbalanced_teams_rejected():
    parts = [participant(i, 100 if i < 6 else 200) for i in range(10)]
    with pytest.raises(ValidationError, match="team=100"):
        MatchPayload(**payload_dict(participants=parts))


def test_played_at_must_be_utc_z():
    with pytest.raises(ValidationError, match="played_at"):
        MatchPayload(**payload_dict(played_at="2026-08-11T20:41:03+03:00"))


def test_invalid_position_rejected():
    part = participant(0, 100)
    part["position"] = "ORTA"
    with pytest.raises(ValidationError, match="position"):
        Participant(**part)


def test_empty_puuid_rejected():
    part = participant(0, 100)
    part["puuid"] = ""
    with pytest.raises(ValidationError):
        Participant(**part)


def test_stats_nullable():
    stats = Stats()
    assert stats.kills is None and stats.cs is None
