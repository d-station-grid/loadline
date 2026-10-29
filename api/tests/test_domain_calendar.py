from datetime import UTC, datetime

from app.domain.calendar import today_for


def test_today_for_uses_the_user_timezone() -> None:
    """UTC の 10/28 16:00 は、東京では 10/29、ロサンゼルスでは 10/28。"""
    now = datetime(2026, 10, 28, 16, 0, tzinfo=UTC)

    assert today_for("Asia/Tokyo", now).isoformat() == "2026-10-29"
    assert today_for("America/Los_Angeles", now).isoformat() == "2026-10-28"
