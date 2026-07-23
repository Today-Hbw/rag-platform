"""runner 单测：run_eval 编排 + run 存取往返（fake 检索器，离线）。"""

from eval.runner import load_run, run_eval, save_run
from eval.schema import EvalCase


def _cases():
    return [
        EvalCase(id="q1", query="社保", relevant_doc_ids=[1]),
        EvalCase(id="q2", query="报销", relevant_doc_ids=[9]),
    ]


def test_run_eval_computes_per_case_and_aggregate():
    # q1 命中 doc 1（top1），q2 检索不到 doc 9
    fake = {"社保": [1, 2, 3], "报销": [5, 6, 7]}
    run = run_eval(_cases(), lambda q: fake[q], ks=(1, 3), name="t")
    assert run.per_case["q1"]["hit_rate@1"] == 1.0
    assert run.per_case["q2"]["hit_rate@3"] == 0.0
    assert run.aggregate["hit_rate@1"] == 0.5  # 1 命中 / 2
    assert run.ranked["q1"] == [1, 2, 3]


def test_save_load_roundtrip(tmp_path):
    run = run_eval(_cases(), lambda q: [1], ks=(1,), name="t", meta={"collection": "snap1"})
    p = tmp_path / "run.json"
    save_run(run, p)
    back = load_run(p)
    assert back.name == "t"
    assert back.meta["collection"] == "snap1"
    assert back.aggregate == run.aggregate
    assert back.ranked["q1"] == [1]
