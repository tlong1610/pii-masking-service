"""PostgresConnector.list_relations feeds the join-key guard and the DPO join-key UI."""

from piimask.connectors import postgres_connector


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, _query, params=None):
        self.params = params

    def fetchall(self):
        return self._rows


class _FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self.cursor_obj


def test_list_relations_reads_declared_foreign_keys(monkeypatch):
    rows = [
        {
            "source_table": "territories",
            "source_column": "region_id",
            "target_table": "region",
            "target_column": "region_id",
        }
    ]
    connection = _FakeConnection(rows)
    opened: list[str] = []

    def fake_connect(url, **_kwargs):
        opened.append(url)
        return connection

    monkeypatch.setattr(postgres_connector.psycopg, "connect", fake_connect)

    relations = postgres_connector.PostgresConnector("postgresql://fake/db").list_relations("public")

    assert relations == [("territories", "region_id", "region", "region_id")]
    assert opened == ["postgresql://fake/db"]
    assert connection.cursor_obj.params == ("public",)
