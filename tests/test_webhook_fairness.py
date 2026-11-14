"""One Client's webhook flood must not take every other Client's turn.

The queue is shared by every channel of every Client, so before lanes a single
Client sending 64 messages filled it and every other Client's webhook got 503.
These run the real worker threads; every blocking job waits on an Event the
``gates`` fixture releases, so a failure cannot leave the shared pool stuck.
"""

import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.routes import telegram_routes, wasender_routes, whatchimp_routes
from app.services.webhook_worker import WEBHOOK_WORKERS, drain, submit

WAIT = 5  # seconds; a hung worker fails the test instead of hanging the suite
A, B = 101, 202  # company ids


@pytest.fixture
def gates():
    made = []

    def gate():
        made.append(threading.Event())
        return made[-1]

    yield gate
    for event in made:
        event.set()
    assert drain(), "webhook worker did not finish"


def held_by(gate, started):
    def work():
        started.append(threading.current_thread().name)
        gate.wait(WAIT)
    return work


def wait_until(condition):
    deadline = time.monotonic() + WAIT
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def saturate(company_id, gate):
    """Submit 100 jobs for one Client: 2 start and hold their workers, the rest queue."""
    started = []
    work = held_by(gate, started)
    accepted = [submit("test", work, company_id) for _ in range(2)]
    assert wait_until(lambda: len(started) == 2), "the first two jobs never started"
    accepted += [submit("test", work, company_id) for _ in range(98)]
    return accepted, started


def hold_every_worker(gate):
    started = []
    for index in range(WEBHOOK_WORKERS):
        assert submit("hold", held_by(gate, started), 9000 + index)
    assert wait_until(lambda: len(started) == WEBHOOK_WORKERS), "workers never all busy"


def test_a_flooding_client_is_capped_at_22_and_another_client_still_runs(gates):
    accepted, started = saturate(A, gates())

    assert accepted == [True] * 22 + [False] * 78  # 2 running + 20 waiting
    done = threading.Event()
    assert submit("test", done.set, B)
    assert done.wait(WAIT), "Client B waited behind Client A's backlog"
    assert len(started) == 2, "Client A ran more than 2 jobs at once"


def test_lanes_take_turns_so_a_later_client_is_not_stuck_behind_a_backlog(gates):
    first, rest = gates(), gates()
    started = []
    assert submit("hold", held_by(first, started), 9000)
    for index in range(1, WEBHOOK_WORKERS):
        assert submit("hold", held_by(rest, started), 9000 + index)
    assert wait_until(lambda: len(started) == WEBHOOK_WORKERS), "workers never all busy"

    order = []
    for name, company_id in (("A1", A), ("A2", A), ("A3", A), ("B", B)):
        assert submit(name, lambda name=name: order.append(name), company_id)
    first.set()  # exactly one worker is free, so it serves the lanes one job at a time

    assert wait_until(lambda: len(order) == 4), "queued jobs never ran"
    assert order == ["A1", "B", "A2", "A3"]


def test_the_whole_queue_still_holds_at_most_64_waiting(gates):
    hold_every_worker(gates())

    accepted = [submit("test", lambda: None, 500 + client) for client in range(5) for _ in range(20)]

    assert accepted.count(True) == 64
    assert accepted[60:] == [True] * 4 + [False] * 36  # the 4th Client gets the last 4 places, the 5th none


# --- the three webhook routes -------------------------------------------------

SECRET_A, SECRET_B, UNKNOWN = "A" * 43, "B" * 43, "C" * 43  # shaped like token_urlsafe(32)
CHANNELS = {SECRET_A: {"id": 1, "company_id": A}, SECRET_B: {"id": 2, "company_id": B}}
ROUTES = {
    "telegram": (telegram_routes, telegram_routes.telegram_blueprint,
                 "assert_telegram_channel_ready", "process_telegram_update", "/telegram/webhook/"),
    "wasender": (wasender_routes, wasender_routes.wasender_blueprint,
                 "get_wasender_channel_by_secret", "process_wasender_webhook", "/wasender/webhook/"),
    "whatchimp": (whatchimp_routes, whatchimp_routes.whatchimp_blueprint,
                  "get_whatchimp_channel_by_secret", "process_whatchimp_webhook", "/whatchimp/webhook/"),
}


@pytest.fixture(params=sorted(ROUTES))
def route(request, monkeypatch):
    module, blueprint, lookup_name, process_name, path = ROUTES[request.param]
    app = Flask(__name__)
    app.register_blueprint(blueprint)
    client = app.test_client()
    process = Mock()
    monkeypatch.setattr(module, lookup_name, CHANNELS.get)
    monkeypatch.setattr(module, process_name, process)

    def post(secret, body):
        return client.post(path + secret, json=body, headers={"X-Telegram-Bot-Api-Secret-Token": secret})

    def fail_lookup(error):
        monkeypatch.setattr(module, lookup_name, Mock(side_effect=error))

    return SimpleNamespace(post=post, process=process, fail_lookup=fail_lookup)


def test_an_over_cap_client_gets_503_and_another_client_gets_200(route, gates):
    gate = gates()
    saturate(A, gate)

    # The payload names Client B; the lane still comes from the secret's own channel.
    blocked = route.post(SECRET_A, {"company_id": B, "update_id": 1})
    served = route.post(SECRET_B, {"update_id": 2})

    assert blocked.status_code == 503
    assert served.status_code == 200
    gate.set()
    assert drain(), "webhook worker did not finish"
    assert [call.args[1] for call in route.process.call_args_list] == [SECRET_B]


def test_a_failed_channel_lookup_answers_503_and_queues_nothing(route, caplog):
    route.fail_lookup(RuntimeError(SECRET_A))

    with caplog.at_level(logging.INFO):
        response = route.post(SECRET_A, {"update_id": 1})

    assert response.status_code == 503
    assert drain(), "webhook worker did not finish"
    route.process.assert_not_called()
    assert SECRET_A not in caplog.text and "RuntimeError" in caplog.text


def test_an_unknown_secret_keeps_its_200_and_takes_no_lane(route):
    response = route.post(UNKNOWN, {"update_id": 1})

    assert response.status_code == 200
    assert drain(), "webhook worker did not finish"
    route.process.assert_not_called()
