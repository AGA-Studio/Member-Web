"""Row Level Security: the database also enforces "a business only sees its rows".

Defense in depth (MVP, issue #74). The application already filters every query
by the `business_id` of the token; RLS makes PostgreSQL refuse the rows of
another business even if a query forgets that filter.

How it works:
- Migration `e4a7b9c1d3f5` creates the role `memberplus_tenant` (NOLOGIN, no
  BYPASSRLS) and one policy per business table, comparing the row with the
  setting `app.business_id`.
- A request that resolves `BusinessId` calls `activate()`. From then on, every
  transaction of that session starts with `SET LOCAL ROLE memberplus_tenant` and
  `app.business_id` = the token's business. `SET LOCAL` ends with the
  transaction, so a pooled connection never carries it to another request.
- The table owner (the login user, a superuser in Docker and Coolify) bypasses
  RLS. That is on purpose: login, the public card, the platform panel, the seed
  and Alembic need rows of every business and never call `activate()`.
- Without `app.business_id`, the tenant role sees no rows (fail closed).

SQLite has no RLS: `activate()` only records the business there.
"""

from sqlalchemy import Connection, event, text
from sqlmodel import Session

TENANT_ROLE = "memberplus_tenant"
SETTING = "app.business_id"
_INFO_KEY = "rls_business_id"

# Business tables and the column that holds the business. Every table with a
# `business_id` must be here (tests/rules/test_rls.py checks it).
TABLES: dict[str, str] = {
    "businesses": "id",
    "users": "business_id",
    "tiers": "business_id",
    "customers": "business_id",
    "purchases": "business_id",
    "card_deliveries": "business_id",
    "card_emails": "business_id",
    "membership_payments": "business_id",
}

# NULLIF: an unset or empty setting compares as NULL, so no row matches.
CURRENT_BUSINESS = f"NULLIF(current_setting('{SETTING}', true), '')::integer"


def enable_statements() -> list[str]:
    """DDL that turns RLS on. The migration keeps its own frozen copy."""
    statements = [
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{TENANT_ROLE}') THEN
                CREATE ROLE {TENANT_ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
            IF NOT pg_has_role(current_user, '{TENANT_ROLE}', 'MEMBER') THEN
                EXECUTE format('GRANT {TENANT_ROLE} TO %I', current_user);
            END IF;
        END
        $$
        """,
        f"GRANT USAGE ON SCHEMA public TO {TENANT_ROLE}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {TENANT_ROLE}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {TENANT_ROLE}",
    ]
    for table, column in TABLES.items():
        statements += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"DROP POLICY IF EXISTS tenant_isolation ON {table}",
            f"CREATE POLICY tenant_isolation ON {table} TO {TENANT_ROLE} "
            f"USING ({column} = {CURRENT_BUSINESS}) "
            f"WITH CHECK ({column} = {CURRENT_BUSINESS})",
        ]
    return statements


def _apply(connection: Connection, business_id: int) -> None:
    connection.execute(text(f"SET LOCAL ROLE {TENANT_ROLE}"))
    connection.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": SETTING, "value": str(business_id)},
    )


def activate(session: Session, business_id: int) -> None:
    """Scope this session to one business for the rest of the request."""
    session.info[_INFO_KEY] = business_id
    connection = session.connection()  # begins a transaction if there is none
    if connection.dialect.name == "postgresql":
        # The current transaction may have begun before this call (the user and
        # the token were already read), so `after_begin` did not cover it.
        _apply(connection, business_id)


@event.listens_for(Session, "after_begin")
def _scope_new_transaction(session: Session, _transaction, connection: Connection) -> None:
    """After a commit or a rollback, the next transaction is scoped again."""
    business_id = session.info.get(_INFO_KEY)
    if business_id is not None and connection.dialect.name == "postgresql":
        _apply(connection, business_id)
