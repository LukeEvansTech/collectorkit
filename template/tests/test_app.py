"""The behaviours every collector keeps, with the sources and the mail stubbed."""

import pytest
from collectorkit import collect, runs
from fastapi.testclient import TestClient
from myapp import config, sweep
from myapp.db import open_db
from myapp.web import create_app


def item(key):
    return collect.Item(key, f"Item {key}", f"https://shop.example/{key}", "£10.00")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MYAPP_DATA", str(tmp_path))
    monkeypatch.setenv("MYAPP_PUBLIC_URL", "https://myapp.example.test")
    monkeypatch.setenv("MYAPP_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("MYAPP_MAIL_FROM", "noreply@example.test")
    monkeypatch.setenv("MYAPP_MAIL_TO", "me@example.test")
    s = config.load()
    state = {"shop": ["1", "2"], "mail": "sent", "sent": []}

    def jobs():
        def read():
            if state["shop"] is None:
                raise TimeoutError("shop down")
            return [item(k) for k in state["shop"]]

        return [("Shop", read)]

    def send(*args):
        if state["mail"] == "sent":
            state["sent"].append(args[4])  # the subject
        return state["mail"]

    monkeypatch.setattr(sweep.sources, "jobs", jobs)
    monkeypatch.setattr(sweep.mail, "send", send)
    monkeypatch.setattr(sweep.notify, "send", lambda *a, **k: "off")
    return s, open_db(s.common.db_path), state


def test_the_first_sweep_is_a_baseline_and_new_listings_are_mailed_once(env):
    s, db, state = env
    sweep.run(db, s)
    assert state["sent"] == []
    state["shop"] = ["1", "2", "3"]
    sweep.run(db, s)
    sweep.run(db, s)
    assert state["sent"] == ["Myapp: 1 new listing"]


def test_a_failed_send_leaves_the_listing_new(env):
    s, db, state = env
    sweep.run(db, s)
    state["shop"], state["mail"] = ["1", "2", "3"], "failed: SMTPConnectError"
    run_id = sweep.run(db, s)
    assert db.one("SELECT alerts FROM runs WHERE id = ?", run_id)["alerts"].startswith("failed")
    state["mail"] = "sent"
    sweep.run(db, s)
    assert state["sent"] == ["Myapp: 1 new listing"]


def test_a_failed_source_is_not_a_success_and_retires_nothing(env):
    s, db, state = env
    sweep.run(db, s)
    before = runs.last_success(db)
    state["shop"] = None
    run_id = sweep.run(db, s)
    assert db.one("SELECT status FROM runs WHERE id = ?", run_id)["status"] == "failed"
    assert runs.coverage(db, run_id) == ["Shop: FAILED (TimeoutError)"]
    assert runs.last_success(db) == before
    assert db.one("SELECT COUNT(*) n FROM listings")["n"] == 2


def test_pages_health_and_metrics(env):
    s, db, _ = env
    sweep.run(db, s)
    client = TestClient(create_app(s, db))
    assert "Item 1" in client.get("/").text
    assert client.get("/health").json()["ok"] is True
    body = client.get("/metrics").text
    assert "myapp_listings 2" in body and "myapp_last_success_timestamp_seconds 0" not in body
    assert client.get("/img/..%2Fmyapp.db").status_code == 404
