"""并行 runner 结果 echo 的回归测试。

顺序 runner（base_runner）会把 expected / description / tags 回写进每个
detail dict（报告据此展示用例描述）；并行 runner 必须保持同一行为，
否则 ParallelJSONRunner 产出的报告缺失 Description 行。
"""

import json

from symtest.runners.parallel_json_runner import ParallelJSONRunner
from symtest.core.test_case import TestCase


def _make_runner(tmp_path) -> ParallelJSONRunner:
    config = tmp_path / "cases.json"
    config.write_text(
        json.dumps({"test_cases": []}),
        encoding="utf-8",
    )
    return ParallelJSONRunner(str(config), workspace=str(tmp_path), max_workers=2)


def _make_case() -> TestCase:
    return TestCase(
        name="T00a_hyper",
        command="python",
        args=["run.py"],
        expected={"return_code": 0},
        description="刚体平移测试",
        tags=["hyper"],
    )


def test_update_results_echoes_expected_description_tags(tmp_path):
    runner = _make_runner(tmp_path)
    result = {"name": "T00a_hyper", "status": "passed", "duration": 1.0}

    runner._update_results(result, 1, _make_case())

    detail = runner.results["details"][0]
    assert detail["description"] == "刚体平移测试"
    assert detail["tags"] == ["hyper"]
    assert detail["expected"] == {"return_code": 0}


def test_update_results_empty_description_maps_to_none(tmp_path):
    runner = _make_runner(tmp_path)
    case = TestCase(name="no_desc", command="echo")
    result = {"name": "no_desc", "status": "passed", "duration": 1.0}

    runner._update_results(result, 1, case)

    detail = runner.results["details"][0]
    assert detail["description"] is None
    assert detail["tags"] == []
    assert detail["expected"] is None


def test_cascade_skip_result_echoes_metadata(tmp_path):
    """依赖失败级联 skip 的结果同样携带 metadata（与顺序 runner 的 skip_result 对齐）。"""
    config = tmp_path / "cases_dag.json"
    config.write_text(
        json.dumps({
            "test_cases": [
                {
                    "name": "dep",
                    "execution": {
                        "command": "python",
                        "args": ["-c", "import sys; sys.exit(1)"],
                    },
                    "expected": {"return_code": 0},
                },
                {
                    "name": "child",
                    "description": "下游用例描述",
                    "scheduling": {"depends_on": ["dep"]},
                    "execution": {"command": "echo", "args": ["hi"]},
                    "expected": {"return_code": 0},
                },
            ]
        }),
        encoding="utf-8",
    )
    runner = ParallelJSONRunner(str(config), workspace=str(tmp_path), max_workers=2)
    runner.run_tests()

    details = {d["name"]: d for d in runner.results["details"]}
    assert details["dep"]["status"] == "failed"
    assert details["child"]["status"] == "skipped"
    assert details["child"]["description"] == "下游用例描述"
    assert details["child"]["expected"] == {"return_code": 0}
