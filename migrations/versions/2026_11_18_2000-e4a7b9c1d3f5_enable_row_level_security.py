"""enable row level security

Revision ID: e4a7b9c1d3f5
Revises: d3f6a8c0e1b2
Create Date: 2026-11-18 20:00:00.000000+00:00

PostgreSQL only (SQLite has no RLS). Creates the role `memberplus_tenant` and
one policy per business table; `db/rls.py` explains how the app uses them. The
SQL is copied here on purpose: a migration must not change when the app does.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4a7b9c1d3f5"
down_revision: str | Sequence[str] | None = "d3f6a8c0e1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "memberplus_tenant"
CURRENT_BUSINESS = "NULLIF(current_setting('app.business_id', true), '')::integer"
TABLES = {
    "businesses": "id",
    "users": "business_id",
    "tiers": "business_id",
    "customers": "business_id",
    "purchases": "business_id",
    "card_deliveries": "business_id",
    "card_emails": "business_id",
    "membership_payments": "business_id",
}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    # Roles belong to the server, not to one database: the dev and test
    # databases share it, so it is created only once.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
            IF NOT pg_has_role(current_user, '{ROLE}', 'MEMBER') THEN
                EXECUTE format('GRANT {ROLE} TO %I', current_user);
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")
    # Tables created by later migrations get the same privileges.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}"
    )
    for table, column in TABLES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} TO {ROLE} "
            f"USING ({column} = {CURRENT_BUSINESS}) "
            f"WITH CHECK ({column} = {CURRENT_BUSINESS})"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
    # Another database of the same server (dev or test) may still use the role:
    # it is dropped only when nothing depends on it.
    op.execute(
        f"""
        DO $$
        BEGIN
            DROP ROLE IF EXISTS {ROLE};
        EXCEPTION WHEN dependent_objects_still_exist THEN
            NULL;
        END
        $$
        """
    )
