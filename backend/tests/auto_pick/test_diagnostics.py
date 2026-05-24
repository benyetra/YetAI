from app.services.auto_pick.diagnostics import summarize_drop_reasons


def test_summarize_drop_reasons():
    dropped = {
        "e1": "below_threshold:58.0",
        "e2": "below_threshold:61.2",
        "e3": "odds_out_of_bounds:500",
    }
    assert summarize_drop_reasons(dropped) == {
        "below_threshold": 2,
        "odds_out_of_bounds": 1,
    }
