"""stages/vectorize.py 单测：切块→编码→ChunkPayload→写入，全离线（fake embedder/store/DB）。"""

from rag_core.settings import Settings
from rag_pipeline.stages import vectorize as vz
from rag_pipeline.workspace import Workspace


class RepoSpy:
    def __init__(self, docs, to_delete=None, manifest=None, old_points=None):
        self._docs = docs
        self._to_delete = to_delete or []
        self._manifest = manifest or {"images": [], "attachments": []}
        self._old_points = old_points or []
        self.vec_status = []
        self.vec_errors = []
        self.chunk_records = []
        self.fully_deleted = []

    def get_docs_to_delete(self, conn):
        return list(self._to_delete)

    def get_chunk_point_ids(self, conn, doc_id):
        return list(self._old_points)

    def mark_doc_fully_deleted(self, conn, doc_id):
        self.fully_deleted.append(doc_id)

    def get_docs_to_vectorize(self, conn):
        return list(self._docs)

    def build_manifest(self, conn, doc_id):
        return self._manifest

    def update_vec_status(self, conn, doc_id, file_hash, chunk_count):
        self.vec_status.append((doc_id, file_hash, chunk_count))

    def update_vec_error(self, conn, doc_id, status, msg):
        self.vec_errors.append((doc_id, status, msg))

    def replace_chunk_records(self, conn, doc_id, chunks_data):
        self.chunk_records.append((doc_id, chunks_data))


class FakeStore:
    def __init__(self):
        self.upserted = []
        self.deleted = []
        self.ensured = False
        self.indexes = None

    def ensure_collection(self, dim, *, recreate=False):
        self.ensured = True
        return True

    def ensure_payload_indexes(self, fields):
        self.indexes = fields

    def upsert(self, points, *, batch_size=10):
        self.upserted.extend(points)

    def delete(self, point_ids):
        self.deleted.extend(point_ids)


class FakeEmbedder:
    def __init__(self, fail_on=None):
        self.calls = []
        self._fail_on = fail_on

    def embed_multimodal(self, text, image_paths=None):
        self.calls.append((text, image_paths))
        if self._fail_on is not None and self._fail_on in text:
            raise RuntimeError("embed boom")
        return [0.1, 0.2, 0.3]


def _settings():
    return Settings()


def _doc(doc_id=5, source_file="20260722/kb_42/md_clean/5_t.md"):
    return {
        "doc_id": doc_id,
        "source": "yuque",
        "namespace": "teamx",
        "collection_id": "42",
        "collection_slug": "kb",
        "doc_key": "d5",
        "doc_title": "标题",
        "source_url": "http://x/5",
        "source_file": source_file,
    }


def _make_bundle(monkeypatch, tmp_path, spy, embedder=None, store=None):
    monkeypatch.setattr(vz, "repository", spy)
    # make_point 依赖 qdrant，替换为纯 dict 便于断言
    monkeypatch.setattr(
        vz, "make_point", lambda pid, vec, payload: {"id": pid, "vec": vec, "payload": payload}
    )
    ws = Workspace(tmp_path, "20260722")
    return ws, embedder or FakeEmbedder(), store or FakeStore()


def _write_clean(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_vectorize_builds_generalized_payload(monkeypatch, tmp_path):
    _write_clean(tmp_path, "20260722/kb_42/md_clean/5_t.md", "正文内容足够有意义")
    spy = RepoSpy(docs=[_doc()])
    ws, emb, store = _make_bundle(monkeypatch, tmp_path, spy)
    stats = vz.vectorize(object(), ws, settings=_settings(), embedder=emb, store=store)

    assert stats.vectorized == 1 and stats.chunks == 1
    assert store.ensured and store.indexes == vz.PAYLOAD_INDEXES
    payload = store.upserted[0]["payload"]
    # 泛化 facets 落顶层键，无旧 team_code/book_id
    assert payload["source"] == "yuque"
    assert payload["collection_id"] == "42"
    assert payload["namespace"] == "teamx"
    assert payload["doc_key"] == "d5"
    assert payload["source_url"] == "http://x/5"  # 直取 doc_meta，未重建模板
    assert "team_code" not in payload and "book_id" not in payload
    assert spy.vec_status[0][0] == 5
    assert spy.chunk_records[0][0] == 5


def test_vectorize_skips_empty(monkeypatch, tmp_path):
    _write_clean(tmp_path, "20260722/kb_42/md_clean/5_t.md", "   \n\n  ")
    spy = RepoSpy(docs=[_doc()])
    ws, emb, store = _make_bundle(monkeypatch, tmp_path, spy)
    stats = vz.vectorize(object(), ws, settings=_settings(), embedder=emb, store=store)
    assert stats.skipped == 1 and stats.vectorized == 0
    assert spy.vec_errors[0][1] == "vec_skipped"
    assert store.upserted == []


def test_vectorize_missing_file_failed(monkeypatch, tmp_path):
    spy = RepoSpy(docs=[_doc(source_file="nope/md_clean/x.md")])
    ws, emb, store = _make_bundle(monkeypatch, tmp_path, spy)
    stats = vz.vectorize(object(), ws, settings=_settings(), embedder=emb, store=store)
    assert stats.failed == 1
    assert spy.vec_errors[0][1] == "vec_failed"


def test_vectorize_embedding_failure_no_partial_write(monkeypatch, tmp_path):
    _write_clean(tmp_path, "20260722/kb_42/md_clean/5_t.md", "有意义的正文")
    spy = RepoSpy(docs=[_doc()])
    emb = FakeEmbedder(fail_on="有意义")
    ws, _, store = _make_bundle(monkeypatch, tmp_path, spy, embedder=emb)
    stats = vz.vectorize(object(), ws, settings=_settings(), embedder=emb, store=store)
    assert stats.failed == 1
    assert store.upserted == []  # 编码失败不写任何点
    assert spy.vec_errors[0][1] == "vec_failed"


def test_vectorize_upsert_new_before_delete_old(monkeypatch, tmp_path):
    _write_clean(tmp_path, "20260722/kb_42/md_clean/5_t.md", "有意义的正文内容")
    spy = RepoSpy(docs=[_doc()], old_points=["old1", "old2"])
    ws, emb, store = _make_bundle(monkeypatch, tmp_path, spy)
    vz.vectorize(object(), ws, settings=_settings(), embedder=emb, store=store)
    assert len(store.upserted) == 1  # 新点已写
    assert store.deleted == ["old1", "old2"]  # 旧点后删


def test_vectorize_processes_deletions_first(monkeypatch, tmp_path):
    spy = RepoSpy(docs=[], to_delete=["9"], old_points=["p9a", "p9b"])
    ws, emb, store = _make_bundle(monkeypatch, tmp_path, spy)
    stats = vz.vectorize(object(), ws, settings=_settings(), embedder=emb, store=store)
    assert stats.deleted == 1
    assert store.deleted == ["p9a", "p9b"]
    assert spy.fully_deleted == [9]
