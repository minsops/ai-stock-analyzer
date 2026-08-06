from __future__ import annotations

from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from config import settings
from scripts import init_db
from src.data_layer.storage import DataStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "stocks",
    "daily_quotes",
    "financial_data",
    "capital_flow",
    "industry_index",
    "scores",
    "news",
    "market_regime",
    "watchlist",
}


def run_upgrade(url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def render_upgrade_sql(url: str) -> str:
    output = StringIO()
    config = Config(str(PROJECT_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head", sql=True)
    return output.getvalue()


def test_alembic_upgrades_empty_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'empty.db'}"

    run_upgrade(url)

    engine = create_engine(url)
    table_names = set(inspect(engine).get_table_names())
    assert table_names >= EXPECTED_TABLES | {"alembic_version"}
    with engine.connect() as connection:
        index_columns = connection.exec_driver_sql(
            "PRAGMA index_xinfo('idx_scores_date_composite')"
        ).all()
    composite_column = next(row for row in index_columns if row[2] == "composite_score")
    assert composite_column[3] == 1


def test_alembic_renders_offline_upgrade_sql(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'offline.db'}"

    sql = render_upgrade_sql(url)

    assert "CREATE TABLE stocks" in sql
    assert "CREATE INDEX idx_scores_date_composite" in sql


def test_alembic_upgrades_existing_unversioned_database(tmp_path: Path) -> None:
    storage = DataStorage(f"sqlite:///{tmp_path / 'existing.db'}")
    storage.init_db()

    run_upgrade(storage.db_url)
    run_upgrade(storage.db_url)

    score_indexes = {item["name"] for item in inspect(storage.engine).get_indexes("scores")}
    assert "idx_scores_date_composite" in score_indexes


def test_alembic_upgrades_legacy_watchlist_columns(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watchlist ("
                "code VARCHAR NOT NULL PRIMARY KEY, "
                "note VARCHAR, "
                "added_at DATETIME NOT NULL)"
            )
        )

    run_upgrade(url)

    columns = {item["name"] for item in inspect(engine).get_columns("watchlist")}
    assert {"group_name", "alert_above", "alert_below"} <= columns


def test_init_script_runs_alembic(tmp_path: Path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'script.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)

    init_db.main()

    assert "alembic_version" in inspect(create_engine(url)).get_table_names()
