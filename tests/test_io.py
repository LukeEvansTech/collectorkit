"""collect, llm, mail and images, with the network stubbed."""

# Stubs keep the signatures of what they replace; the parsers return plain lists.
# pylint: disable=unused-argument,unbalanced-tuple-unpacking

import email
import io
import json
import smtplib

import pytest
from collectorkit import collect, images, llm, mail
from PIL import Image


def jpeg(colour="red", size=(800, 400), fmt="JPEG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, fmt)
    return out.getvalue()


# --- collect ---
WOO = [
    {
        "id": 501,
        "name": "Goku &amp; Broly 1/4",
        "permalink": "https://shop.test/product/goku",
        "prices": {"price": "45000", "currency_minor_unit": 2, "currency_symbol": "£"},
        "images": [{"src": "https://shop.test/goku.jpg"}],
        "categories": [{"name": "Dragon Ball"}],
        "tags": [{"name": "Pre-order"}],
    },
    {"id": 502, "name": "No price", "permalink": "https://shop.test/product/x", "prices": {}},
]


def test_woo_items_reads_price_photo_and_tags():
    a, b = collect.woo_items(WOO)
    assert (a.key, a.name, a.price) == ("501", "Goku & Broly 1/4", "£450.00")
    assert a.image == "https://shop.test/goku.jpg" and a.tags == ["Dragon Ball", "Pre-order"]
    assert (b.price, b.image, b.tags) == ("", "", [])


def test_woo_reads_the_newest_pages(monkeypatch):
    asked = []

    def fake(url, timeout=40):
        asked.append(url)
        return json.dumps(WOO if "page=1" in url else [])

    monkeypatch.setattr(collect, "http_get", fake)
    assert len(collect.woo("https://shop.test/")) == 2
    assert (
        asked[0].startswith("https://shop.test/wp-json/wc/store/v1/products?") and len(asked) == 2
    )


def test_shopify_items_builds_the_product_url_and_takes_either_tag_form():
    data = {
        "products": [
            {
                "id": 9,
                "title": "GMK Set",
                "handle": "gmk-set",
                "product_type": "Keycaps",
                "tags": "group-buy, abs",
                "variants": [{"price": "120.00"}],
                "images": [{"src": "https://cdn.test/a.jpg"}],
            },
            {"id": 10, "title": "Bare", "handle": "bare", "tags": ["in-stock"]},
        ]
    }
    a, b = collect.shopify_items(data, "https://keys.test/")
    assert a.url == "https://keys.test/products/gmk-set" and a.price == "120.00"
    assert a.tags == ["Keycaps", "group-buy", "abs"] and a.key == "9"
    assert (b.price, b.image, b.tags) == ("", "", ["in-stock"])


def test_page_items_filters_rewrites_and_dedupes():
    rows = [
        ["https://s.test/p/one?ref=a", "One", "https://s.test/img/thumb/1.jpg", "£10"],
        ["https://s.test/p/one/", "One again", "https://s.test/img/thumb/1b.jpg", "£10"],
        ["https://s.test/about", "Logo", "https://s.test/img/thumb/logo.jpg", ""],
        ["https://s.test/p/two", "Two", "https://s.test/banner.jpg", ""],
    ]
    got = collect.page_items(rows, href_match=r"/p/", img_match=r"/img/", img_sub=("thumb", "full"))
    assert [(i.key, i.image) for i in got] == [
        ("https://s.test/p/one", "https://s.test/img/full/1.jpg")
    ]


def test_page_items_can_key_on_the_query_string():
    rows = [
        ["https://s.test/item?itemCode=1", "One", "https://s.test/1.jpg", ""],
        ["https://s.test/item?itemCode=2", "Two", "https://s.test/2.jpg", ""],
    ]
    assert len(collect.page_items(rows)) == 1
    assert [i.name for i in collect.page_items(rows, keep_query=True)] == ["One", "Two"]


def test_http_get_refuses_other_schemes():
    with pytest.raises(ValueError):
        collect.http_get("file:///etc/passwd")


def test_run_records_a_failure_and_an_empty_read_as_failures():
    def boom():
        raise TimeoutError("slow shop")

    got = collect.run(
        [
            ("Good", lambda: [collect.Item("1", "A", "https://s.test/1")]),
            ("Dead", boom),
            ("Empty", lambda: []),
        ]
    )
    good, dead, empty = got
    assert good.error is None and good.items[0].source == "Good"
    assert dead.items is None and dead.error == "TimeoutError"  # the type, never the text
    assert empty.items is None and "0 items" in empty.error


# --- llm ---
class FakeResponse:
    def __init__(self, body, headers=None):
        self.body, self.headers = json.dumps(body).encode(), headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answer(text):
    return {"choices": [{"message": {"content": text}}]}


def test_ask_sends_the_photo_and_counts_cost(monkeypatch):
    sent = {}

    def fake(req, timeout):
        sent["url"], sent["auth"] = req.full_url, req.get_header("Authorization")
        sent["body"] = json.loads(req.data)
        return FakeResponse(answer('Sure: {"ok": true}'), {"x-litellm-response-cost": "0.0125"})

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    model = llm.LLM("http://litellm.test/v1/", "k", "claude")
    assert model.ask("Is it?", [jpeg()]) == {"ok": True}
    assert sent["url"] == "http://litellm.test/v1/chat/completions" and sent["auth"] == "Bearer k"
    parts = sent["body"]["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Is it?"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert (model.usage.calls, model.usage.cost) == (1, 0.0125)


def test_a_failed_call_is_none_not_an_answer(monkeypatch, caplog):
    def fake(req, timeout):
        raise OSError("connection refused with key k-secret")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    model = llm.LLM("http://litellm.test/v1", "k-secret", "claude")
    assert model.complete("x") is None and model.ask("x") is None
    assert model.usage.calls == 0 and "k-secret" not in caplog.text


def test_a_photo_gone_from_the_volume_is_none_not_a_crash(tmp_path):
    model = llm.LLM("http://litellm.test/v1", "k", "claude")
    assert model.ask("x", [tmp_path / "gone.jpg"]) is None and model.usage.calls == 0


def test_an_answer_without_json_is_none_and_off_without_a_url(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen", lambda req, timeout: FakeResponse(answer("no"))
    )
    assert llm.LLM("http://litellm.test/v1", "k", "claude").ask("x") is None
    assert llm.parse_json("[1, 2]") is None
    off = llm.LLM("", "", "claude")
    assert off.on is False and off.complete("x") is None


# --- mail ---
class FakeSMTP:
    sent: list = []
    refuse: dict = {}

    def __init__(self, host, port, timeout):
        self.where = (host, port)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def has_extn(self, name):
        return False

    def send_message(self, msg):
        FakeSMTP.sent.append((self.where, msg))
        return FakeSMTP.refuse


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.refuse = [], {}
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_send_carries_the_photo_inline(smtp):
    photos = mail.Photos(domain="toys")
    assert photos.add("a.jpg", mail.thumb(jpeg())) is True
    assert photos.add("gone.jpg", None) is False and photos.src("gone.jpg") == ""
    html = f'<img src="{photos.src("a.jpg")}">'
    res = mail.send(
        "smtp.test",
        25,
        "noreply@example.test",
        "me@example.test",
        "3 new",
        html,
        "3 new",
        photos,
        "Toys",
    )
    assert res == "sent"
    where, msg = smtp.sent[0]
    assert where == ("smtp.test", 25) and msg["From"] == "Toys <noreply@example.test>"
    parsed = email.message_from_bytes(msg.as_bytes())
    inline = [p for p in parsed.walk() if p.get_content_type() == "image/jpeg"]
    assert len(inline) == 1 and inline[0]["Content-ID"].strip("<>") == photos.src("a.jpg")[4:]


def test_photos_stop_at_the_limit():
    photos = mail.Photos(limit=1)
    assert photos.add("a", b"x") and not photos.add("b", b"y") and photos.add("a", b"x")


def test_a_refused_recipient_or_a_dead_relay_is_a_failure(smtp, monkeypatch):
    smtp.refuse = {"me@example.test": (550, b"no")}
    args = ("smtp.test", 25, "noreply@example.test", "me@example.test", "s", "<p>h</p>", "t")
    assert mail.send(*args) == "failed: 1 recipient(s) refused"

    def dead(host, port, timeout):
        raise smtplib.SMTPConnectError(421, "down")

    monkeypatch.setattr(mail.smtplib, "SMTP", dead)
    assert mail.send(*args) == "failed: SMTPConnectError"


def test_a_subject_with_a_line_break_is_a_failure_not_a_crash(smtp):
    res = mail.send(
        "smtp.test", 25, "a@example.test", "b@example.test", "one\ntwo", "<p>h</p>", "t"
    )
    assert res.startswith("failed: ") and not smtp.sent


def test_thumb_shrinks_and_survives_rubbish(tmp_path):
    small = Image.open(io.BytesIO(mail.thumb(jpeg(), side=100)))
    assert max(small.size) == 100
    f = tmp_path / "p.png"
    f.write_bytes(jpeg(fmt="PNG"))
    assert mail.thumb(f)[:3] == b"\xff\xd8\xff"
    assert mail.thumb(b"not an image") is None


# --- images ---
def test_as_jpeg_converts_a_png_served_under_any_name():
    out = images.as_jpeg(jpeg(fmt="PNG"), max_side=200)
    assert out[:3] == b"\xff\xd8\xff" and max(Image.open(io.BytesIO(out)).size) == 200
    assert images.as_jpeg(b"<html>blocked</html>") is None


def test_store_names_by_content_and_download_survives_a_dead_url(tmp_path, monkeypatch, caplog):
    raw = jpeg()
    name = images.store(raw, tmp_path)
    assert name.endswith(".jpg") and images.store(raw, tmp_path) == name
    assert max(Image.open(tmp_path / name).size) == images.MAX_SIDE
    with pytest.raises(ValueError):
        images.store(b"nope", tmp_path)
    with pytest.raises(ValueError):
        images.fetch("file:///etc/passwd")

    monkeypatch.setattr(images, "fetch", lambda url, referer="": raw)
    assert images.download("https://s.test/a.jpg", tmp_path) == name

    def dead(url, referer=""):
        raise OSError("gone")

    monkeypatch.setattr(images, "fetch", dead)
    assert images.download("https://s.test/a.jpg?sig=secret-token", tmp_path) == ""
    assert "s.test" in caplog.text and "secret-token" not in caplog.text
    assert images.download("", tmp_path) == ""
    assert images.download("https://[broken/a.jpg", tmp_path) == ""


def test_a_sideways_photo_is_turned_upright():
    out = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees to display
    Image.new("RGB", (80, 40), "red").save(out, "JPEG", exif=exif)
    assert Image.open(io.BytesIO(images.as_jpeg(out.getvalue()))).size == (40, 80)
    assert Image.open(io.BytesIO(mail.thumb(out.getvalue()))).size == (40, 80)


def test_an_image_that_claims_to_be_enormous_is_not_an_image(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # the 800x400 test photo is 320 times that
    assert images.as_jpeg(jpeg()) is None and mail.thumb(jpeg()) is None
