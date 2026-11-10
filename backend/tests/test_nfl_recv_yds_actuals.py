from app.services.etl.nfl.collect_recv_yds_actuals import grade_recv_row


def test_grade_recv_row_error_and_ou_hit():
    out = grade_recv_row(actual_yards=90.0, predicted=85.0, ou_line=80.0)
    assert out["prediction_error"] == 5.0
    assert out["hit_over_under"] is True


def test_grade_recv_row_null_line():
    out = grade_recv_row(actual_yards=90.0, predicted=85.0, ou_line=None)
    assert out["hit_over_under"] is None
