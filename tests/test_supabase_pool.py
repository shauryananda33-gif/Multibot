from supabase_db import _PostgresConnection

class FakeConnection:
    def __init__(self, fail_commit=False):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_commit = fail_commit
    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        self.closed = True

class FakePool:
    def __init__(self):
        self.returned = []
    def putconn(self, connection):
        self.returned.append(connection)

def test_pooled_connection_commits_and_returns_connection():
    raw, pool = FakeConnection(), FakePool()
    with _PostgresConnection(raw, pool=pool):
        pass
    assert raw.commits == 1 and raw.rollbacks == 0
    assert pool.returned == [raw] and not raw.closed

def test_pooled_connection_rolls_back_and_returns_connection():
    raw, pool = FakeConnection(), FakePool()
    try:
        with _PostgresConnection(raw, pool=pool):
            raise ValueError("operation failed")
    except ValueError:
        pass
    assert raw.commits == 0 and raw.rollbacks == 1
    assert pool.returned == [raw]

def test_pooled_connection_discards_uncertain_connection_on_commit_error():
    import pytest
    raw, pool = FakeConnection(fail_commit=True), FakePool()
    with pytest.raises(RuntimeError, match="commit failed"):
        with _PostgresConnection(raw, pool=pool):
            pass
    assert raw.closed and pool.returned == [raw]
