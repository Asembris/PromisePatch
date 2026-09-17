"""What PostgreSQL refuses to let the application do to itself.

Every assertion here is provoked against a real database and identified by SQLSTATE, because
the point of this boundary is that it holds for code nobody has written yet. An enforcement
that lives in a repository method protects the callers who remember to use that method; a
trigger and a privilege protect the migration, the console session and the future service too.

The tests run under two identities on purpose. ``conn`` is the migration role, which owns the
schema and can therefore show what the triggers refuse even to an administrator. ``app_conn``
is ``promisepatch_app``, the login the running system actually uses, and the only identity that
can honestly answer "what can this application do".

Sweeps over many tables run inside savepoints rather than one connection per case: a rejected
statement aborts its transaction, and a savepoint is what lets the next assertion still happen.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Executable, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from promisepatch.db.boundary import (
    APPEND_ONLY_TABLES,
    AUDIT_MARKER,
    GOVERNED_TABLES,
    MIGRATION_ONLY_TABLES,
    READINESS_READABLE_TABLES,
    RUNTIME_ROLE,
    RUNTIME_SEQUENCES,
    SUPABASE_API_ROLES,
    TRUNCATE_PROTECTED_TABLES,
    UNGOVERNED_TABLES,
    all_tables,
    runtime_privileges,
)
from promisepatch.db.models import AuditEvent, InventoryLedgerEntry, Recipe, RecipeVersion, Resource
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork

pytestmark = pytest.mark.integration

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
INSUFFICIENT_PRIVILEGE = "42501"
SYSTEM = Actor(kind="SYSTEM", id="database-protection-tests")

# A column that exists on each append-only table, so a forbidden statement can be written
# without a row to aim it at: the guard is statement-level and fires either way.
APPEND_ONLY_COLUMN = {
    "approval_decisions": "raw_text",
    "audit_events": "type",
    "case_reports": "raw_text",
    "domain_events": "type",
    "exception_facts": "target_id",
    "inventory_ledger": "source_id",
    "plan_approvals": "evidence",
    "recipe_version_equipment": "equipment_id",
    "recipe_version_lines": "role",
    "recipe_versions": "authored_by",
}


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def sql_list(values: Iterable[str]) -> str:
    """A SQL literal list built from module constants -- never from anything a caller supplies."""
    return ", ".join(f"'{value}'" for value in values)


def sqlstate(error: DBAPIError) -> str:
    """The code the database itself reported, not the sentence the driver wrapped it in."""
    return str(getattr(error.orig, "sqlstate", ""))


async def refused(conn: AsyncConnection, statement: str) -> DBAPIError:
    """Run a statement that must fail, inside a savepoint so the transaction survives it."""
    savepoint = await conn.begin_nested()
    try:
        await conn.exec_driver_sql(statement)
    except DBAPIError as error:
        await savepoint.rollback()
        return error
    await savepoint.rollback()
    raise AssertionError(f"the database accepted a statement it must refuse: {statement}")


def governed(connection: AsyncConnection, **overrides: Any) -> Any:
    """A governed block with the uninteresting parts filled in."""
    arguments: dict[str, Any] = {
        "event_type": "FIXTURE_LOAD",
        "actor": SYSTEM,
        "authority": "NONE",
    }
    arguments.update(overrides)
    return UnitOfWork(connection).governed(**arguments)


def a_resource(resource_id: str) -> Executable:
    return insert(Resource).values(id=resource_id, kind="INGREDIENT", name="raspberries", unit="kg")


async def a_recipe_version(write: GovernedWrite) -> str:
    recipe_id, version_id = unique("rec"), unique("rv")
    await write.execute(insert(Recipe).values(id=recipe_id, name="Cake"))
    await write.execute(
        insert(RecipeVersion).values(
            id=version_id,
            recipe_id=recipe_id,
            version_no=1,
            authored_by="jo",
            authored_at=NOW,
        )
    )
    return version_id


# --------------------------------------------------------------------- the governed boundary


async def test_an_ungoverned_insert_is_rejected(app_conn: AsyncConnection) -> None:
    """The whole boundary in one statement: no audit event, no write."""
    with pytest.raises(DBAPIError, match="ungoverned write") as caught:
        await app_conn.execute(a_resource(unique("res")))
    assert sqlstate(caught.value) == INSUFFICIENT_PRIVILEGE


async def test_every_ungoverned_statement_shape_is_rejected(app_conn: AsyncConnection) -> None:
    """Insert, update and delete are one boundary, not three habits."""
    for statement in (
        "insert into promisepatch.resources (id, kind, name, unit)"
        " values ('res-x', 'INGREDIENT', 'x', 'kg')",
        "update promisepatch.resources set name = name where false",
        "delete from promisepatch.resources where false",
    ):
        error = await refused(app_conn, statement)
        assert sqlstate(error) == INSUFFICIENT_PRIVILEGE
        assert "ungoverned write" in str(error)


async def test_an_unaudited_truncate_is_rejected(conn: AsyncConnection) -> None:
    """Emptying a governed table is a write like any other, and needs the same authority.

    Aimed at a table nothing references: PostgreSQL checks inbound foreign keys before it fires
    the trigger, and a refusal to truncate half a graph would not prove anything about audit.
    """
    with pytest.raises(DBAPIError, match="ungoverned write") as caught:
        await conn.exec_driver_sql("truncate table promisepatch.reservations")
    assert sqlstate(caught.value) == INSUFFICIENT_PRIVILEGE


async def test_a_marker_naming_no_audit_event_is_rejected(app_conn: AsyncConnection) -> None:
    """Setting the transaction-local marker by hand authorises nothing."""
    await app_conn.execute(
        text(f"select set_config('{AUDIT_MARKER}', :marker, true)"),
        {"marker": "9223372036854775807"},
    )
    with pytest.raises(DBAPIError, match="stale audit marker") as caught:
        await app_conn.execute(a_resource(unique("res")))
    assert sqlstate(caught.value) == INSUFFICIENT_PRIVILEGE


async def test_an_audit_event_from_another_transaction_is_rejected(
    app_conn: AsyncConnection,
) -> None:
    """The audit row must belong to *this* transaction, not merely exist.

    The row inserted here is visible, well formed, and names a real transaction — just not the
    one doing the writing. Without the ``pg_current_xact_id()`` comparison, a marker left over
    from any earlier committed write would go on authorising new ones indefinitely.
    """
    stale_seq = await app_conn.scalar(
        text(
            "insert into promisepatch.audit_events"
            " (id, xid, type, actor_kind, authority, correlation_id)"
            " values (gen_random_uuid(), '3'::xid8, 'FORGED', 'SYSTEM', 'NONE', gen_random_uuid())"
            " returning seq"
        )
    )
    await app_conn.execute(
        text(f"select set_config('{AUDIT_MARKER}', :marker, true)"), {"marker": str(stale_seq)}
    )
    with pytest.raises(DBAPIError, match="stale audit marker") as caught:
        await app_conn.execute(a_resource(unique("res")))
    assert sqlstate(caught.value) == INSUFFICIENT_PRIVILEGE


async def test_a_marker_that_is_not_a_sequence_number_is_rejected(
    app_conn: AsyncConnection,
) -> None:
    await app_conn.execute(
        text(f"select set_config('{AUDIT_MARKER}', :marker, true)"), {"marker": "definitely"}
    )
    with pytest.raises(DBAPIError, match="unusable audit marker") as caught:
        await app_conn.execute(a_resource(unique("res")))
    assert sqlstate(caught.value) == INSUFFICIENT_PRIVILEGE


async def test_a_governed_write_succeeds_and_is_bound_to_its_audit_event(
    app_conn: AsyncConnection,
) -> None:
    resource_id = unique("res")
    async with governed(app_conn, event_type="PHYSICAL_FACT_RECORDED") as write:
        await write.execute(a_resource(resource_id))

    assert await app_conn.scalar(select(Resource.id).where(Resource.id == resource_id))
    bound = await app_conn.scalar(
        select(AuditEvent.seq).where(
            AuditEvent.seq == write.audit_seq,
            AuditEvent.xid == text("pg_current_xact_id()"),
        )
    )
    assert bound == write.audit_seq


async def test_the_authorisation_does_not_outlive_the_block_that_took_it_out(
    app_conn: AsyncConnection,
) -> None:
    """One audit event authorises one governed block, not the rest of the transaction."""
    async with governed(app_conn) as write:
        await write.execute(a_resource(unique("res")))

    with pytest.raises(DBAPIError, match="ungoverned write") as caught:
        await app_conn.execute(a_resource(unique("res")))
    assert sqlstate(caught.value) == INSUFFICIENT_PRIVILEGE


async def test_a_rolled_back_governed_write_leaves_neither_half(app_engine: AsyncEngine) -> None:
    """Audit row and domain write share one fate: both, or neither."""
    resource_id = unique("res")
    async with app_engine.connect() as writer:
        await writer.begin()
        async with governed(writer) as write:
            await write.execute(a_resource(resource_id))
            audit_seq = write.audit_seq
        await writer.rollback()

    async with app_engine.connect() as reader:
        assert await reader.scalar(select(Resource.id).where(Resource.id == resource_id)) is None
        assert (
            await reader.scalar(select(AuditEvent.seq).where(AuditEvent.seq == audit_seq)) is None
        )


async def test_an_ungoverned_table_still_takes_an_unaudited_write(
    app_conn: AsyncConnection,
) -> None:
    """The boundary is selective.

    An inbound webhook is stored before anyone has decided anything about it, so requiring an
    audit event to record its arrival would be auditing a decision nobody has taken.
    """
    event_id = uuid4()
    await app_conn.execute(
        text(
            "insert into promisepatch.inbox_events"
            " (id, source, provider_event_id, received_at, state)"
            " values (:id, 'telegram', :provider, now(), 'RECEIVED')"
        ),
        {"id": event_id, "provider": unique("upd")},
    )
    assert await app_conn.scalar(
        text("select count(*) from promisepatch.inbox_events where id = :id"), {"id": event_id}
    )


# ------------------------------------------------------------------------------ immutability


async def test_an_authored_recipe_version_cannot_be_rewritten(conn: AsyncConnection) -> None:
    """Immutability outranks authorisation: a valid governed transaction still cannot edit.

    Run as the migration role on purpose. The runtime role has no UPDATE privilege here at all,
    so only an identity that *could* issue the statement can show the trigger refusing it.
    """
    async with governed(conn) as write:
        version_id = await a_recipe_version(write)
        error = await refused(
            conn,
            f"update promisepatch.recipe_versions set authored_by = 'someone else'"
            f" where id = '{version_id}'",
        )
    assert sqlstate(error) == INSUFFICIENT_PRIVILEGE
    assert "append-only" in str(error)


async def test_an_authored_recipe_version_cannot_be_deleted(conn: AsyncConnection) -> None:
    async with governed(conn) as write:
        version_id = await a_recipe_version(write)
        error = await refused(
            conn, f"delete from promisepatch.recipe_versions where id = '{version_id}'"
        )
    assert sqlstate(error) == INSUFFICIENT_PRIVILEGE
    assert "append-only" in str(error)


async def test_a_physical_posting_cannot_be_edited_after_the_fact(conn: AsyncConnection) -> None:
    """On-hand is the sum of the ledger, so an editable ledger is stock nobody can trust."""
    resource_id = unique("res")
    async with governed(conn) as write:
        await write.execute(a_resource(resource_id))
        await write.execute(
            insert(InventoryLedgerEntry).values(
                resource_id=resource_id,
                delta=Decimal("6.000"),
                source_kind="COMMITMENT_RECEIPT",
                source_id=unique("cl"),
                recorded_at=NOW,
            )
        )
        update = await refused(
            conn,
            f"update promisepatch.inventory_ledger set delta = 0"
            f" where resource_id = '{resource_id}'",
        )
        delete = await refused(
            conn,
            f"delete from promisepatch.inventory_ledger where resource_id = '{resource_id}'",
        )
    assert sqlstate(update) == sqlstate(delete) == INSUFFICIENT_PRIVILEGE
    assert "append-only" in str(update)
    assert "append-only" in str(delete)


async def test_a_replayed_physical_posting_is_still_refused_when_audited(
    app_conn: AsyncConnection,
) -> None:
    """Exactly-once is a constraint, not a convention — and authority does not suspend it."""
    resource_id, source_id = unique("res"), unique("cl")
    posting = {
        "resource_id": resource_id,
        "delta": Decimal("6.000"),
        "source_kind": "COMMITMENT_RECEIPT",
        "source_id": source_id,
        "recorded_at": NOW,
    }
    async with governed(app_conn) as write:
        await write.execute(a_resource(resource_id))
        await write.execute(insert(InventoryLedgerEntry).values(**posting))
        with pytest.raises(IntegrityError, match="uq_inventory_ledger_source"):
            await write.execute(insert(InventoryLedgerEntry).values(**posting))


async def test_the_runtime_role_is_refused_a_rewrite_before_the_trigger_is_reached(
    app_conn: AsyncConnection,
) -> None:
    """Two layers, one answer.

    The application is not merely stopped from rewriting a ledger by a trigger it might one day
    find a way past: it has never held the privilege to issue the statement. Both refusals are
    ``42501``, which is the point — the caller cannot tell, and does not need to.
    """
    for statement in (
        "update promisepatch.inventory_ledger set delta = 0 where false",
        "delete from promisepatch.inventory_ledger where false",
        "update promisepatch.recipe_versions set authored_by = 'x' where false",
        "update promisepatch.audit_events set type = type where false",
    ):
        error = await refused(app_conn, statement)
        assert sqlstate(error) == INSUFFICIENT_PRIVILEGE, statement
        assert "permission denied" in str(error), statement


async def test_no_append_only_table_accepts_an_update_or_a_delete(conn: AsyncConnection) -> None:
    """Asserted for the whole set, so a ninth ledger cannot be added without a guard."""
    for table, column in sorted(APPEND_ONLY_COLUMN.items()):
        assert table in APPEND_ONLY_TABLES
        for statement in (
            f"update promisepatch.{table} set {column} = {column} where false",
            f"delete from promisepatch.{table} where false",
        ):
            error = await refused(conn, statement)
            assert sqlstate(error) == INSUFFICIENT_PRIVILEGE
            assert "append-only" in str(error), statement
    assert set(APPEND_ONLY_COLUMN) == set(APPEND_ONLY_TABLES)


async def test_a_ledger_of_record_cannot_be_emptied(conn: AsyncConnection) -> None:
    """No authority empties the audit ledger or the event spine. There is no such authority."""
    for table in sorted(TRUNCATE_PROTECTED_TABLES):
        error = await refused(conn, f"truncate table promisepatch.{table}")
        assert sqlstate(error) == INSUFFICIENT_PRIVILEGE
        assert "append-only" in str(error), table


# -------------------------------------------------------------------------- trigger coverage

BEFORE_STATEMENT = 2
ON_INSERT, ON_DELETE, ON_UPDATE, ON_TRUNCATE = 4, 8, 16, 32

EXPECTED_TRIGGERS = {
    "trg_00_append_only": BEFORE_STATEMENT | ON_UPDATE | ON_DELETE,
    "trg_01_no_truncate": BEFORE_STATEMENT | ON_TRUNCATE,
    "trg_10_governed_write": BEFORE_STATEMENT | ON_INSERT | ON_UPDATE | ON_DELETE,
    "trg_11_governed_truncate": BEFORE_STATEMENT | ON_TRUNCATE,
}


async def installed_triggers(conn: AsyncConnection) -> dict[str, dict[str, int]]:
    """Every non-internal trigger in the schema, by table and name."""
    rows = (
        await conn.exec_driver_sql(
            "select c.relname, t.tgname, t.tgtype, t.tgenabled"
            " from pg_trigger t"
            " join pg_class c on c.oid = t.tgrelid"
            " join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'promisepatch' and not t.tgisinternal"
        )
    ).all()
    found: dict[str, dict[str, int]] = {}
    for table, name, tgtype, enabled in rows:
        # `tgenabled` is a "char" column, which asyncpg hands back as a single byte.
        mode = enabled.decode() if isinstance(enabled, bytes) else str(enabled)
        assert mode == "O", f"{table}.{name} is not enabled in origin mode"
        found.setdefault(table, {})[name] = int(tgtype)
    return found


async def test_every_governed_table_carries_the_write_and_truncate_guards(
    conn: AsyncConnection,
) -> None:
    installed = await installed_triggers(conn)
    missing = {
        table: sorted(
            name
            for name in ("trg_10_governed_write", "trg_11_governed_truncate")
            if installed.get(table, {}).get(name) != EXPECTED_TRIGGERS[name]
        )
        for table in sorted(GOVERNED_TABLES)
    }
    assert {table: names for table, names in missing.items() if names} == {}


async def test_every_append_only_table_carries_the_mutation_guard(conn: AsyncConnection) -> None:
    installed = await installed_triggers(conn)
    unguarded = [
        table
        for table in sorted(APPEND_ONLY_TABLES)
        if installed.get(table, {}).get("trg_00_append_only")
        != EXPECTED_TRIGGERS["trg_00_append_only"]
    ]
    assert unguarded == []

    untruncatable = [
        table
        for table in sorted(TRUNCATE_PROTECTED_TABLES)
        if installed.get(table, {}).get("trg_01_no_truncate")
        != EXPECTED_TRIGGERS["trg_01_no_truncate"]
    ]
    assert untruncatable == []


async def test_no_ungoverned_table_carries_the_write_guard(conn: AsyncConnection) -> None:
    """Coverage is asserted in both directions, so the boundary cannot quietly widen either."""
    installed = await installed_triggers(conn)
    overreach = {
        table: sorted(set(installed.get(table, {})) & {"trg_10_governed_write"})
        for table in sorted(UNGOVERNED_TABLES)
    }
    assert {table: names for table, names in overreach.items() if names} == {}


async def test_immutability_is_evaluated_before_authorisation(conn: AsyncConnection) -> None:
    """PostgreSQL fires same-timing triggers in name order, and the names encode the order.

    On a table that is both governed and append-only, ``trg_00_append_only`` must sort first, so
    a forbidden rewrite is reported as immutable rather than as unaudited whichever way the
    transaction was authorised.
    """
    installed = await installed_triggers(conn)
    for table in sorted(APPEND_ONLY_TABLES & GOVERNED_TABLES):
        names = sorted(installed[table])
        assert names[0] == "trg_00_append_only", table


# ----------------------------------------------------------------------- the runtime identity


async def test_the_runtime_role_holds_no_dangerous_attribute(conn: AsyncConnection) -> None:
    row = (
        await conn.exec_driver_sql(
            "select rolsuper, rolcreatedb, rolcreaterole, rolbypassrls,"
            " rolreplication, rolcanlogin"
            f" from pg_roles where rolname = '{RUNTIME_ROLE}'"
        )
    ).one()
    superuser, createdb, createrole, bypassrls, replication, canlogin = row
    assert not any((superuser, createdb, createrole, bypassrls, replication))
    assert canlogin


async def test_the_runtime_role_owns_nothing_in_the_schema(conn: AsyncConnection) -> None:
    """A role that owns a table can drop that table's triggers, which would end the argument."""
    owned = await conn.scalar(
        text(
            "select count(*) from pg_class c"
            " join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'promisepatch'"
            " and c.relowner = (select oid from pg_roles where rolname = :role)"
        ),
        {"role": RUNTIME_ROLE},
    )
    assert owned == 0


async def test_the_runtime_role_may_use_the_schema_but_not_extend_it(
    conn: AsyncConnection,
) -> None:
    usage, create = (
        await conn.exec_driver_sql(
            f"select has_schema_privilege('{RUNTIME_ROLE}', 'promisepatch', 'USAGE'),"
            f" has_schema_privilege('{RUNTIME_ROLE}', 'promisepatch', 'CREATE')"
        )
    ).one()
    assert usage
    assert not create


async def test_the_runtime_role_privilege_matrix_is_exactly_as_intended(
    conn: AsyncConnection,
) -> None:
    """Append-only ledgers get no way to rewrite themselves; bookkeeping is out of reach."""
    candidates = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    tables = sorted(all_tables() | MIGRATION_ONLY_TABLES)
    rows = (
        await conn.exec_driver_sql(
            f"select t.name, p.privilege,"
            f" has_table_privilege('{RUNTIME_ROLE}', 'promisepatch.' || t.name, p.privilege)"
            f" from unnest(array[{sql_list(tables)}]::text[]) as t(name)"
            f" cross join unnest(array[{sql_list(candidates)}]::text[]) as p(privilege)"
        )
    ).all()

    granted: dict[str, set[str]] = {table: set() for table in tables}
    for table, privilege, held in rows:
        if held:
            granted[table].add(privilege)

    assert granted == {table: set(runtime_privileges(table)) for table in tables}


async def test_the_runtime_role_may_read_the_revision_but_not_claim_one(
    app_conn: AsyncConnection,
) -> None:
    """Readiness must compare revisions over the connection that serves requests.

    Asserted as the runtime role itself rather than through ``has_table_privilege``, because
    the question is whether the probe works, not whether a catalogue says it should.
    """
    for table in sorted(READINESS_READABLE_TABLES):
        revision = await app_conn.scalar(text(f'select version_num from promisepatch."{table}"'))
        assert revision

    error = await refused(
        app_conn,
        "insert into promisepatch.alembic_version (version_num) values ('9999_forged')",
    )
    assert sqlstate(error) == INSUFFICIENT_PRIVILEGE


async def test_the_runtime_role_may_draw_from_a_sequence_but_not_rewind_it(
    conn: AsyncConnection,
) -> None:
    """``UPDATE`` on a sequence is ``setval``: a ledger whose numbering could be replayed."""
    for sequence in sorted(RUNTIME_SEQUENCES):
        held = {
            privilege
            for privilege in ("USAGE", "SELECT", "UPDATE")
            if await conn.scalar(
                text("select has_sequence_privilege(:role, :sequence, :privilege)"),
                {
                    "role": RUNTIME_ROLE,
                    "sequence": f"promisepatch.{sequence}",
                    "privilege": privilege,
                },
            )
        }
        assert held == {"USAGE"}, sequence


async def test_the_runtime_role_cannot_reach_around_the_triggers(
    app_conn: AsyncConnection,
) -> None:
    """The enforcement has to be out of reach of the identity it constrains.

    Disabling one trigger needs ownership; ``session_replication_role`` would silence every
    trigger in the session at once and needs a superuser. The application is neither.

    Migration bookkeeping is reachable for reading and for nothing else: since
    ``0003_runtime_readiness_access`` the runtime role may see which revision ran, so what is
    asserted here is that it still cannot rewrite one and so cannot misrepresent its schema.
    """
    for statement in (
        "alter table promisepatch.resources disable trigger trg_10_governed_write",
        "set session_replication_role = 'replica'",
        "update promisepatch.alembic_version set version_num = '9999_forged'",
        "delete from promisepatch.alembic_version",
    ):
        error = await refused(app_conn, statement)
        assert sqlstate(error) == INSUFFICIENT_PRIVILEGE, statement


# ------------------------------------------------------------------------- the managed host


async def test_no_managed_api_role_can_reach_the_private_schema(conn: AsyncConnection) -> None:
    """These roles back an automatic REST layer, and our schema must be invisible to them."""
    checked = 0
    for role in SUPABASE_API_ROLES:
        if not await conn.scalar(
            text("select count(*) from pg_roles where rolname = :role"), {"role": role}
        ):
            continue
        checked += 1
        for privilege in ("USAGE", "CREATE"):
            assert not await conn.scalar(
                text("select has_schema_privilege(:role, 'promisepatch', :privilege)"),
                {"role": role, "privilege": privilege},
            ), f"{role} holds {privilege} on the promisepatch schema"

        reachable = (
            await conn.execute(
                text(
                    "select c.relname from pg_class c"
                    " join pg_namespace n on n.oid = c.relnamespace"
                    " where n.nspname = 'promisepatch' and c.relkind in ('r', 'S')"
                    " and (has_table_privilege(:role, c.oid, 'SELECT')"
                    "      or has_table_privilege(:role, c.oid, 'INSERT'))"
                ),
                {"role": role},
            )
        ).all()
        assert reachable == [], role
    assert checked, "no managed API role exists on this host; the assertion proved nothing"


async def test_the_schema_grants_nothing_by_default_to_tables_added_later(
    conn: AsyncConnection,
) -> None:
    """A default ACL would hand every table added after today to whoever it names."""
    defaults = (
        await conn.exec_driver_sql(
            "select d.defaclacl::text from pg_default_acl d"
            " join pg_namespace n on n.oid = d.defaclnamespace"
            " where n.nspname = 'promisepatch'"
        )
    ).all()
    assert defaults == []
