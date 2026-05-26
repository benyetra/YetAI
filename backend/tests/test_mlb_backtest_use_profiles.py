from app.services.etl.mlb.backtest.cli import parse_args


def test_parse_args_use_profiles():
    args = parse_args(["--quick", "--use-profiles"])
    assert args.use_profiles is True
    assert args.quick is True
