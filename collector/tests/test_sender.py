import json

import httpx

from collector.sender import SendOutcome, Sender


def make_payload(game_id="111"):
    return {"source": "lcu_eog", "source_game_id": game_id, "participants": []}


def make_sender(config, status_or_handler):
    if callable(status_or_handler):
        handler = status_or_handler
    else:
        handler = lambda request: httpx.Response(status_or_handler, json={})
    return Sender(config, transport=httpx.MockTransport(handler))


def test_send_success_201(config):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"match_id": 1, "duplicate": False})

    sender = make_sender(config, handler)
    assert sender.send(make_payload()) is SendOutcome.OK
    request = requests[0]
    assert request.url.path == "/api/v1/ingest/match"
    assert request.headers["X-API-Key"] == "test-key"
    assert json.loads(request.content)["source_game_id"] == "111"


def test_send_duplicate_200_is_ok(config):
    sender = make_sender(config, lambda r: httpx.Response(200, json={"match_id": 1, "duplicate": True}))
    assert sender.send(make_payload()) is SendOutcome.OK


def test_send_network_error_is_retry(config):
    def handler(request):
        raise httpx.ConnectError("bağlanamadı")

    sender = make_sender(config, handler)
    assert sender.send(make_payload()) is SendOutcome.RETRY


def test_send_500_is_retry_and_writes_outbox(config):
    sender = make_sender(config, 500)
    assert sender.send_or_outbox(make_payload("222")) is SendOutcome.RETRY
    outbox_file = config.outbox_dir / "222.json"
    assert outbox_file.is_file()
    assert json.loads(outbox_file.read_text(encoding="utf-8"))["source_game_id"] == "222"


def test_send_422_goes_to_rejected(config):
    sender = make_sender(config, lambda r: httpx.Response(422, json={"detail": "şema ihlali"}))
    assert sender.send_or_outbox(make_payload("333")) is SendOutcome.REJECTED
    assert (config.outbox_dir / "rejected" / "333.json").is_file()
    assert not (config.outbox_dir / "333.json").exists()


def test_outbox_retry_cycle(config):
    """DoD senaryosu: 500 → dosya yazılır → sonraki turda 2xx → gönderilir → dosya silinir."""
    sender_down = make_sender(config, 500)
    sender_down.send_or_outbox(make_payload("444"))
    assert (config.outbox_dir / "444.json").is_file()

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(201, json={"match_id": 7, "duplicate": False})

    sender_up = make_sender(config, handler)
    sender_up.flush_outbox()
    assert sent[0]["source_game_id"] == "444"
    assert not (config.outbox_dir / "444.json").exists()


def test_flush_moves_rejected_and_stops_on_retry(config):
    config.outbox_dir.mkdir(parents=True)
    (config.outbox_dir / "a.json").write_text(json.dumps(make_payload("a")), encoding="utf-8")
    (config.outbox_dir / "b.json").write_text(json.dumps(make_payload("b")), encoding="utf-8")
    (config.outbox_dir / "c.json").write_text(json.dumps(make_payload("c")), encoding="utf-8")

    responses = iter([422, 500])

    def handler(request):
        return httpx.Response(next(responses, 500), json={"detail": "x"})

    sender = make_sender(config, handler)
    sender.flush_outbox()
    # a → 422 → rejected'a taşındı; b → 500 → durdu; c hiç denenmedi, yerinde
    assert (config.outbox_dir / "rejected" / "a.json").is_file()
    assert (config.outbox_dir / "b.json").is_file()
    assert (config.outbox_dir / "c.json").is_file()


def test_flush_empty_outbox_noop(config):
    sender = make_sender(config, 500)
    sender.flush_outbox()  # dizin yokken hata fırlatmamalı
