import tomllib

import market_briefing
from market_briefing.pipeline import PipelineResult


def test_package_version_is_defined():
    assert market_briefing.__version__ == "0.1.0"


def test_pipeline_main_is_callable():
    from market_briefing.pipeline import main

    assert callable(main)


def test_package_data_includes_static_javascript():
    pyproject = tomllib.loads(open("pyproject.toml", encoding="utf-8").read())

    package_data = pyproject["tool"]["setuptools"]["package-data"]["market_briefing"]

    assert "static/*.js" in package_data


def test_pytest_uses_project_temp_dir_and_disables_cacheprovider():
    pyproject = tomllib.loads(open("pyproject.toml", encoding="utf-8").read())

    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]

    assert "--basetemp=pytest-tmp" in addopts
    assert "-p no:cacheprovider" in addopts


def test_project_ignores_pytest_temp_dir():
    gitignore = open(".gitignore", encoding="utf-8").read().splitlines()

    assert "pytest-tmp/" in gitignore


def test_project_ignores_local_handoff_files():
    gitignore = open(".gitignore", encoding="utf-8").read().splitlines()

    assert "codex-to-claude.md" in gitignore
    assert "claude-to-codex.md" in gitignore


def test_pipeline_result_documents_success_and_failure_contract():
    assert PipelineResult.__doc__ is not None
    assert "report is set only when validation_errors is empty" in PipelineResult.__doc__
    assert "validation failed before files were written" in PipelineResult.__doc__
