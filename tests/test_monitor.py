import datetime

from monitor import History, Flight


def test_history():
    flight = Flight("a", "b", datetime.datetime.now())
    h = History()
    h.next_round()
    assert not h.should_skip(flight)
    h.track(flight)
    assert h.should_skip(flight)
    h.next_round()
    assert h.should_skip(flight)
    h.next_round()
    assert h.should_skip(flight)
    h.next_round()
    h.next_round()  # now the history state for `flight` should clear
    assert not h.should_skip(flight)
