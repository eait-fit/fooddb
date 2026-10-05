import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("dev_env", Path(__file__).parents[1] / "scripts" / "dev_env.py")
dev_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev_env)


def test_database_names_per_slot_and_branch():
    assert dev_env.db_name_for(0, "main") == "fooddb"
    assert dev_env.db_name_for(3, "feat/OFF-Deltas") == "fooddb_feat_off_deltas"
    # The double underscore no branch can produce keeps test and dev databases apart.
    assert dev_env.test_db_name_for(dev_env.db_name_for(1, "fix")) == "fooddb_fix__test"
    assert dev_env.db_name_for(1, "fix_test") != dev_env.test_db_name_for(dev_env.db_name_for(1, "fix"))


def test_a_hand_edited_database_name_is_refused():
    values = {"FOODDB_DB_NAME": 'x"; drop database fooddb; --', "FOODDB_TEST_DB_NAME": "x__test",
              "FOODDB__BACKEND__API_PORT": "9990"}
    with pytest.raises(SystemExit, match="database name"):
        dev_env.safe(values)


def test_app_refuses_to_guess_a_database(monkeypatch):
    from fooddb import db

    monkeypatch.delenv("FOODDB__BACKEND__DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="FOODDB__BACKEND__DATABASE_URL"):
        db.database_url()
