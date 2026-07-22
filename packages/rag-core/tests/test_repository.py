import rag_core.repository as repo


class FakeCursor:
    def __init__(self, result_sets):
        self._results = list(result_sets)  # 每次 execute 弹一个结果集
        self.calls = []  # [(sql, params), ...]
        self._last = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._last = self._results.pop(0) if self._results else []

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)


class FakeConn:
    def __init__(self, result_sets=None):
        self.cur = FakeCursor(result_sets or [])
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def _sql(conn, i=0):
    return conn.cur.calls[i][0]


def test_table_name_constants():
    assert repo.TABLE_DOC_META == "rag_doc_meta"
    assert repo.TABLE_RESOURCE == "rag_resource"
    assert repo.TABLE_CHUNK == "rag_chunk_record"


def test_upsert_uses_generalized_columns_and_commits():
    conn = FakeConn()
    record = {k: None for k in [
        "doc_id", "source", "namespace", "collection_id", "collection_slug", "doc_key",
        "doc_title", "source_url", "source_file", "source_version", "source_dims",
        "md_hash", "file_hash", "chunk_count", "image_count", "attachment_count",
        "status", "download_time",
    ]}
    repo.upsert_doc_meta(conn, record)
    sql, params = conn.cur.calls[0]
    assert "INSERT INTO rag_doc_meta" in sql
    assert "namespace" in sql and "collection_id" in sql and "source_version" in sql
    assert "qdrant_yuque" not in sql  # 不再有旧表名
    assert "team_code" not in sql and "book_id" not in sql  # 不再有旧列名
    assert params is record
    assert conn.commits == 1


def test_get_docs_to_vectorize_brings_source_url():
    conn = FakeConn([[{"doc_id": 1, "source_url": "u"}]])
    rows = repo.get_docs_to_vectorize(conn)
    assert rows == [{"doc_id": 1, "source_url": "u"}]
    sql = _sql(conn)
    assert "source_url" in sql and "status = 'cleaned'" in sql and "rag_doc_meta" in sql


def test_get_docs_to_delete_returns_str_ids():
    conn = FakeConn([[{"doc_id": 10}, {"doc_id": 20}]])
    assert repo.get_docs_to_delete(conn) == ["10", "20"]


def test_get_scope_versions_maps_doc_id_to_version():
    conn = FakeConn([[
        {"doc_id": 1, "source_version": "v1"},
        {"doc_id": "2", "source_version": None},
    ]])
    out = repo.get_scope_versions(conn, "yuque", 42)
    assert out == {1: "v1", 2: ""}  # doc_id 转 int，None → ""
    sql, params = conn.cur.calls[0]
    assert "status != 'deleted'" in sql and "collection_id" in sql
    assert params == ("yuque", "42")  # collection_id 转 str


def test_mark_docs_deleted_soft_marks_two_tables_and_clears_resources():
    conn = FakeConn()
    repo.mark_docs_deleted(conn, ["3", 4])
    tables = [c[0] for c in conn.cur.calls]
    assert any("UPDATE rag_doc_meta SET status = 'deleted'" in s for s in tables)
    assert any("UPDATE rag_chunk_record SET status = 'deleted'" in s for s in tables)
    assert any("DELETE FROM rag_resource" in s for s in tables)  # 经 delete_resources_for_docs
    # 参数转 int
    assert conn.cur.calls[0][1] == (3, 4)


def test_mark_docs_deleted_empty_is_noop():
    conn = FakeConn()
    repo.mark_docs_deleted(conn, [])
    assert conn.cur.calls == []
    assert conn.commits == 0


def test_save_resources_deletes_then_inserts_with_mapping():
    conn = FakeConn()
    resources = [{"index": 2, "url": "u", "local_path": "p.png", "mime": "image/png"}]
    repo.save_resources(conn, 7, "image", resources)
    del_sql, del_params = conn.cur.calls[0]
    assert del_sql.startswith("DELETE FROM rag_resource") or "DELETE FROM rag_resource" in del_sql
    assert del_params == (7, "image")
    ins_sql, ins_params = conn.cur.calls[1]
    assert "INSERT INTO rag_resource" in ins_sql
    assert ins_params["res_index"] == 2
    assert ins_params["local_file"] == "p.png"  # local_path → local_file
    assert ins_params["file_type"] == "image/png"  # mime → file_type 回退
    assert conn.commits == 1


def test_build_manifest_shape():
    images = [{"res_index": 0, "local_file": "i.png"}]
    atts = [{"res_index": 0, "filename": "a.pdf", "served_url": "/assets/a"}]
    conn = FakeConn([images, atts])
    m = repo.build_manifest(conn, 1)
    assert m["images"][0]["local_path"] == "i.png"
    assert m["attachments"][0]["served_url"] == "/assets/a"
    assert m["attachments"][0]["filename"] == "a.pdf"


def test_mark_doc_fully_deleted_hits_three_tables():
    conn = FakeConn()
    repo.mark_doc_fully_deleted(conn, 5)
    tables = [c[0] for c in conn.cur.calls]
    assert any("rag_chunk_record" in s for s in tables)
    assert any("rag_resource" in s for s in tables)
    assert any("rag_doc_meta" in s for s in tables)
    assert conn.commits == 1


def test_get_chunk_point_ids():
    conn = FakeConn([[{"point_id": "p1"}, {"point_id": "p2"}]])
    assert repo.get_chunk_point_ids(conn, 1) == ["p1", "p2"]
    assert "status = 'active'" in _sql(conn)


def test_replace_chunk_records_delete_then_insert():
    conn = FakeConn()
    repo.replace_chunk_records(conn, 3, [(0, "pid0", "h0"), (1, "pid1", "h1")])
    assert "DELETE FROM rag_chunk_record" in conn.cur.calls[0][0]
    assert conn.cur.calls[1][1] == (3, 0, "pid0", "h0")
    assert conn.cur.calls[2][1] == (3, 1, "pid1", "h1")
    assert conn.commits == 1


def test_delete_resources_for_docs_empty_is_noop():
    conn = FakeConn()
    repo.delete_resources_for_docs(conn, [])
    assert conn.cur.calls == []
    assert conn.commits == 0


def test_delete_resources_for_docs_builds_in_clause():
    conn = FakeConn()
    repo.delete_resources_for_docs(conn, ["1", "2", "3"])
    sql, params = conn.cur.calls[0]
    assert "IN (%s,%s,%s)" in sql
    assert params == (1, 2, 3)  # 转 int
    assert conn.commits == 1
