"""Row Level Security covers every business table (db/rls.py, issue #74).

A new table with `business_id` and no policy would be readable by every
business through the tenant role. The behaviour tests would not notice, since
the application filter still works: this rule does.
"""

from importlib import import_module

from sqlmodel import SQLModel

import models  # noqa: F401  (registers every table in the metadata)
from db import rls
from tests.rules.helpers import ROOT

MIGRATION = "migrations.versions.2026_11_18_2000-e4a7b9c1d3f5_enable_row_level_security"


def business_tables() -> dict[str, str]:
    tables = {"businesses": "id"}
    for table in SQLModel.metadata.sorted_tables:
        if "business_id" in table.columns:
            tables[table.name] = "business_id"
    return tables


def test_every_business_table_has_a_policy() -> None:
    missing = set(business_tables()) - set(rls.TABLES)
    assert not missing, (
        f"Tables with business_id and no RLS policy: {sorted(missing)}. Add them to "
        "db/rls.py TABLES and create their policy in a new migration."
    )


def test_policies_use_the_business_column() -> None:
    assert rls.TABLES == business_tables()


def test_the_migration_covers_the_same_tables() -> None:
    """The migration keeps a frozen copy; a later table needs its own migration."""
    assert (ROOT / "migrations").is_dir()
    migration = import_module(MIGRATION)
    assert migration.TABLES.items() <= rls.TABLES.items()
    assert migration.ROLE == rls.TENANT_ROLE
