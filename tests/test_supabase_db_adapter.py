from supabase_db import _translate_sql


def test_positional_parameters_translate_to_psycopg():
    assert _translate_sql("SELECT * FROM accounts WHERE name=? LIMIT ?") == (
        "SELECT * FROM accounts WHERE name=%s LIMIT %s"
    )


def test_insert_ignore_becomes_postgres_on_conflict():
    sql = _translate_sql("INSERT OR IGNORE INTO accounts VALUES(?,?,?,?,?,?)")
    assert sql == "INSERT INTO accounts VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING"


def test_insert_replace_becomes_keyed_upsert():
    sql = _translate_sql(
        "INSERT OR REPLACE INTO app_config(config_key,payload,updated_at) VALUES(?,?,?)"
    )
    assert sql == (
        'INSERT INTO app_config(config_key,payload,updated_at) VALUES(%s,%s,%s) '
        'ON CONFLICT ("config_key") DO UPDATE SET '
        '"payload" = EXCLUDED."payload", "updated_at" = EXCLUDED."updated_at"'
    )


def test_json_account_lookup_uses_postgres_jsonb():
    sql = _translate_sql("SELECT count(*) FROM trades WHERE json_extract(payload,'$.account')=?")
    assert sql == "SELECT count(*) FROM trades WHERE (payload::jsonb ->> 'account')=%s"


def test_regular_postgres_upsert_is_preserved():
    sql = _translate_sql(
        "INSERT INTO trades VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status"
    )
    assert sql == (
        "INSERT INTO trades VALUES(%s,%s,%s,%s) "
        "ON CONFLICT(id) DO UPDATE SET status=excluded.status"
    )

def test_postgres_cursor_preserves_sqlite_named_and_positional_row_access():
    from supabase_db import _PostgresCursor

    class Column:
        def __init__(self, name):
            self.name = name

    class Cursor:
        description = [Column("owner_id"), Column("expires_at")]
        rowcount = 1
        lastrowid = None

        def fetchone(self):
            return ("worker-a", 123.0)

        def fetchall(self):
            return [("worker-a", 123.0)]

        def fetchmany(self, size=None):
            return [("worker-a", 123.0)]

    row = _PostgresCursor(Cursor()).fetchone()
    assert row[0] == "worker-a"
    assert row["owner_id"] == "worker-a"
    assert row["expires_at"] == 123.0
    assert "owner_id" in row.keys()

