import market_briefing


def test_package_version_is_defined():
    assert market_briefing.__version__ == "0.1.0"


def test_pipeline_main_is_callable():
    from market_briefing.pipeline import main

    assert callable(main)
