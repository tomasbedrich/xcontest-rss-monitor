import datetime

from monitor import History, Flight


def test_history():
    flight = Flight("a", "b", datetime.datetime.now())
    h = History()

    h.next_round()
    assert flight not in h

    h.next_round()
    h.add(flight)
    assert flight in h

    h.next_round()
    h.add(flight)
    assert flight in h

    h.next_round()
    h.add(flight)
    assert flight in h

    h.next_round()
    # assert flight in h
    # ^^^ do NOT run this assert, because it triggers the "touch"

    h.next_round()  # now the history state for `flight` should clear
    assert flight not in h
