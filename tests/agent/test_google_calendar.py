"""Call-backs on Google Calendar: the event, when it is sent, and that a calendar never breaks a call-back."""

import asyncio

import pytest

from ai_agent_service.runtime import google_calendar as gc

BOOKED = {"callback_id": "CB0001", "customer_phone": "0984726714", "callback_at": "2026-10-27T09:00",
          "moved_from": "2026-10-26T09:00", "note": "Tư vấn máy lọc không khí"}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "shop@group.calendar.google.com")
    monkeypatch.setenv("GOOGLE_CALENDAR_CREDENTIALS_JSON", "{}")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/telesales")


def test_the_event_is_at_the_booked_time_in_vietnam_and_says_it_was_moved():
    body = gc.event_body(BOOKED, customer_name="Nguyễn Thị Hoa", phone="0984726714", calendar_id="cal",
                         console_url="https://shop.example/ban-hang/hen-goi-lai")
    assert body["start"] == {"dateTime": "2026-10-27T09:00:00+07:00", "timeZone": "Asia/Ho_Chi_Minh"}
    assert body["end"]["dateTime"] == "2026-10-27T09:15:00+07:00"
    assert body["summary"] == "Gọi lại Nguyễn Thị Hoa (số đuôi 6714)"
    assert "Tư vấn máy lọc không khí" in body["description"]
    assert "đã dời" in body["description"]
    assert "https://shop.example/ban-hang/hen-goi-lai" in body["description"]


def test_the_whole_number_never_leaves_for_google():
    body = gc.event_body(BOOKED, customer_name=None, phone="0984726714", calendar_id="cal")
    assert "0984726714" not in repr(body)
    assert body["summary"] == "Gọi lại (số đuôi 6714)"


def test_the_same_call_back_is_the_same_event_id_in_googles_alphabet():
    first = gc.event_id("cal", "CB0001")
    assert first == gc.event_id("cal", "CB0001") != gc.event_id("cal", "CB0002")
    assert set(first) <= set("0123456789abcdefghijklmnopqrstuv") and 5 <= len(first) <= 1024


def test_off_without_a_calendar_or_a_key_or_on_an_evaluation_database(configured, monkeypatch):
    assert gc.enabled()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/telesales_eval")
    assert not gc.enabled()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/telesales")
    monkeypatch.delenv("GOOGLE_CALENDAR_CREDENTIALS_JSON")
    assert not gc.enabled()
    monkeypatch.setenv("GOOGLE_CALENDAR_CREDENTIALS", "/secrets/key.json")
    monkeypatch.delenv("GOOGLE_CALENDAR_ID")
    assert not gc.enabled()


def test_reminders_are_what_the_setting_says_and_a_bad_entry_is_left_out():
    assert gc.reminders(None) == [{"method": "popup", "minutes": 10}]
    assert gc.reminders("popup:10, email:60") == [{"method": "popup", "minutes": 10},
                                                  {"method": "email", "minutes": 60}]
    assert gc.reminders("sms:5,popup:x,email:99999,popup:30") == [{"method": "popup", "minutes": 30}]
    assert gc.reminders("") == []
    assert len(gc.reminders(",".join(f"popup:{n}" for n in range(9)))) == gc.MAX_REMINDERS


def test_invited_consultants_are_attendees_and_get_googles_email(configured, monkeypatch):
    body = gc.event_body(BOOKED, customer_name=None, phone=None, calendar_id="cal",
                         attendee_spec="a@shop.vn, b@shop.vn,  ", reminder_spec="email:30")
    assert body["attendees"] == [{"email": "a@shop.vn"}, {"email": "b@shop.vn"}]
    assert body["reminders"] == {"useDefault": False, "overrides": [{"method": "email", "minutes": 30}]}
    assert "attendees" not in gc.event_body(BOOKED, customer_name=None, phone=None, calendar_id="cal")

    monkeypatch.setenv("GOOGLE_CALENDAR_ATTENDEES", "a@shop.vn")
    sent = _send(monkeypatch, _Response(200, {"id": "abc"}))
    gc.add_callback(BOOKED, customer_phone=None)
    assert sent[0][1]["params"] == {"sendUpdates": "all"}


def test_an_invite_without_workspace_says_what_to_set(configured, monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_CALENDAR_ATTENDEES", "a@shop.vn")
    _send(monkeypatch, _Response(403, text='{"error":{"errors":[{"reason":"forbiddenForServiceAccounts"}]}}'))
    assert gc.add_callback(BOOKED, customer_phone=None) is None
    assert "GOOGLE_CALENDAR_SUBJECT" in caplog.text


class _Response:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload or {}, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _send(monkeypatch, response):
    sent = []
    monkeypatch.setattr(gc, "_token", lambda: "token")
    monkeypatch.setattr("httpx.post", lambda url, **kw: sent.append((url, kw)) or response)
    return sent


def test_a_call_back_is_posted_to_the_shared_calendar(configured, monkeypatch):
    sent = _send(monkeypatch, _Response(200, {"id": "abc", "htmlLink": "https://calendar.google.com/x"}))
    assert gc.add_callback(BOOKED, customer_phone="0984726714") == {
        "event_id": "abc", "html_link": "https://calendar.google.com/x"}
    url, kw = sent[0]
    assert url == "https://www.googleapis.com/calendar/v3/calendars/shop%40group.calendar.google.com/events"
    assert kw["headers"] == {"Authorization": "Bearer token"}
    assert kw["params"] == {"sendUpdates": "none"}


def test_a_replayed_call_back_finds_its_event_there(configured, monkeypatch):
    _send(monkeypatch, _Response(409))
    assert gc.add_callback(BOOKED, customer_phone="0984726714")["event_id"] == gc.event_id(
        "shop@group.calendar.google.com", "CB0001")


def test_a_calendar_that_fails_is_a_warning_not_a_failed_call_back(configured, monkeypatch, caplog):
    _send(monkeypatch, _Response(403))
    assert gc.add_callback(BOOKED, customer_phone="0984726714") is None
    assert "not put on Google Calendar" in caplog.text


def test_nothing_is_started_when_off(monkeypatch):
    monkeypatch.delenv("GOOGLE_CALENDAR_ID", raising=False)
    monkeypatch.setattr(gc, "add_callback", lambda *a, **k: pytest.fail("sent while off"))

    async def book():
        gc.add_callback_later(BOOKED, customer_phone="0984726714")

    asyncio.run(book())
    assert not gc._pending
