"""encrypt existing plaintext credentials in place

The only migration in this series that rewrites live rows, so it is written to
be boring: idempotent, reversible, and a complete no-op on a database that has
nothing to migrate.

Scope (plan §10.4):
  - external_credentials.credential_data
  - user_configurations.configuration          (LLM / TTS / STT provider keys)
  - organization_configurations.value          (SECRET_BEARING_KEYS only)

Four properties that make this safe:

  1. **Guarded.** Every row is checked with is_sealed() first, so an
     already-encrypted row is skipped rather than double-wrapped. Running this
     twice does nothing the second time.
  2. **Selective on organization_configurations.** That table is a general
     key/value store — disposition mappings and call limits are not secrets,
     and sealing them would make them opaque to the queries that read them.
     The key list is imported from the read path rather than restated, so the
     two cannot drift.
  3. **Fails loudly, never silently.** If rows need encrypting and no
     CREDENTIAL_ENCRYPTION_KEY is configured, this raises. A migration that
     quietly left credentials in plaintext while reporting success would be
     worse than one that stops.
  4. **Reports what it did.** Counts per table, printed, so the operator can
     compare against expectation rather than trusting a silent success.

On a database with nothing to encrypt this touches no rows and does not require
a key to be configured at all.

Revision ID: c93a17e5d248
Revises: b2d5f8a341c7
Create Date: 2026-08-08

"""

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c93a17e5d248"
down_revision: Union[str, None] = "b2d5f8a341c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _secret_bearing_keys() -> set[str]:
    """The organization_configuration keys that carry credential material.

    Imported from the read path rather than restated here — if the two drifted,
    this migration would encrypt a key the reader does not unseal, or leave one
    in plaintext that it does.
    """
    from api.db.organization_configuration_client import SECRET_BEARING_KEYS

    return set(SECRET_BEARING_KEYS)


def _rows_needing_work(connection) -> dict[str, list]:
    """Collect every plaintext row across all three scopes, before touching any.

    Gathered up front so the key check below can fail *before* the first write
    rather than partway through.
    """
    from api.services.crypto import is_sealed

    secret_keys = _secret_bearing_keys()
    work: dict[str, list] = {
        "external_credentials": [],
        "user_configurations": [],
        "organization_configurations": [],
    }

    for row_id, value in connection.execute(
        sa.text("SELECT id, credential_data FROM external_credentials")
    ):
        if isinstance(value, dict) and value and not is_sealed(value):
            work["external_credentials"].append((row_id, value))

    for row_id, value in connection.execute(
        sa.text("SELECT id, configuration FROM user_configurations")
    ):
        if isinstance(value, dict) and value and not is_sealed(value):
            work["user_configurations"].append((row_id, value))

    for row_id, key, value in connection.execute(
        sa.text("SELECT id, key, value FROM organization_configurations")
    ):
        if key not in secret_keys:
            continue
        if isinstance(value, dict) and value and not is_sealed(value):
            work["organization_configurations"].append((row_id, value))

    return work


def _update(connection, table: str, column: str, row_id: Any, value: dict) -> None:
    connection.execute(
        sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
        {"value": json.dumps(value), "id": row_id},
    )


def upgrade() -> None:
    from api.services.crypto import seal_credential_data
    from api.services.crypto.secrets import ENCRYPTION_KEY_ENV_VAR, _load_key

    connection = op.get_bind()
    work = _rows_needing_work(connection)
    total = sum(len(rows) for rows in work.values())

    if total == 0:
        print(
            "[credential-encryption] nothing to encrypt — no plaintext "
            "credentials found. No rows touched."
        )
        return

    # Fail before the first write, not partway through, and say exactly what
    # is missing rather than surfacing a decrypt error later.
    try:
        _load_key()
    except Exception as exc:
        raise RuntimeError(
            f"{total} plaintext credential row(s) need encrypting but "
            f"{ENCRYPTION_KEY_ENV_VAR} is not usable: {exc}. "
            "Set it before running this migration; refusing to continue and "
            "leave credentials in plaintext."
        ) from exc

    columns = {
        "external_credentials": "credential_data",
        "user_configurations": "configuration",
        "organization_configurations": "value",
    }

    counts: dict[str, int] = {}
    for table, rows in work.items():
        for row_id, value in rows:
            _update(connection, table, columns[table], row_id, seal_credential_data(value))
        counts[table] = len(rows)

    print(f"[credential-encryption] encrypted {total} row(s): {counts}")


def downgrade() -> None:
    """Decrypt back to plaintext.

    Exists so the upgrade is reversible, not because reverting is a good idea —
    going back puts credentials in the clear again. Requires the same
    CREDENTIAL_ENCRYPTION_KEY the rows were sealed with.
    """
    from api.services.crypto import is_sealed, unseal_credential_data

    connection = op.get_bind()
    secret_keys = _secret_bearing_keys()
    reverted = 0

    for table, column, key_column in (
        ("external_credentials", "credential_data", None),
        ("user_configurations", "configuration", None),
        ("organization_configurations", "value", "key"),
    ):
        select_columns = f"id, {column}" + (f", {key_column}" if key_column else "")
        for row in connection.execute(
            sa.text(f"SELECT {select_columns} FROM {table}")
        ).fetchall():
            row_id, value = row[0], row[1]
            if key_column and row[2] not in secret_keys:
                continue
            if not is_sealed(value):
                continue
            _update(connection, table, column, row_id, unseal_credential_data(value))
            reverted += 1

    print(f"[credential-encryption] reverted {reverted} row(s) to plaintext.")
