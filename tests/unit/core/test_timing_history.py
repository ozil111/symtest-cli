"""Cold memory learning, timing baseline maturity and CPU accounting flow."""
import json
import os
from unittest.mock import patch

import pytest

from symtest.core.execution.result import ExecutionResult
from symtest.core.history_store import check_regression, load_history
from symtest.core.orchestration.single import execute_single_test_case
from symtest.core.orchestration.sequence import execute_sequence
from symtest.core.test_case import ExecutionSpec, TestStep
from symtest.runners import ParallelJSONRunner


def test_memory_warmup_then_timing_then_scheduling(tmp_path, caplog):
    config = tmp_path / 'cases.json'
    config.write_text(json.dumps({'test_cases': [
        {'name': n, 'execution': {'command': 'echo', 'args': []},
         'expected': {'return_code': 0}} for n in ['short', 'long']
    ]}))
    peak_key = 'max_peak_memory_bytes' if os.name == 'nt' else 'max_peak_memory_bytes_linux'
    source = 'windows_job_commit' if os.name == 'nt' else 'linux_cgroup_v2'
    history_dir = str(tmp_path / 'history')
    for run in range(1, 6):
        runner = ParallelJSONRunner(str(config), workspace=str(tmp_path), history_dir=history_dir)
        runner.load_test_cases()
        # Exercise policy independently of host memory/cgroup availability.
        runner._memory_enabled = True
        runner._memory_history = load_history(history_dir)['cases']
        if run == 2:
            assert [c.name for c in runner.test_cases] == ['short', 'long']
        if run == 3:
            assert [c.name for c in runner.test_cases] == ['long', 'short']
        runner.results['details'] = [
            {'name': n, 'status': 'passed', 'duration': d,
             'cpu_time': d / 2, 'peak_memory_bytes': 100,
             'peak_memory_source': source}
            for n, d in [('short', 1 if run < 5 else 10), ('long', 2)]
        ]
        caplog.clear()
        runner._update_history()
        rec = load_history(history_dir)['cases']['short']
        assert rec[peak_key] == 100
        assert rec.get('run_count', 0) == run - 1
        assert rec.get('cpu_run_count', 0) == run - 1
        assert ('regressed:' in caplog.text) == (run == 5)


@pytest.mark.parametrize('count,warning', [(0, False), (1, False), (2, False), (3, True)])
def test_three_prior_samples_required(count, warning):
    hist = {'cases': {'a': {'avg_duration': 1, 'run_count': count}}}
    assert (check_regression(hist, 'a', 10) is not None) == warning


@pytest.mark.parametrize('cpu_count,cpu_time,expected', [
    (0, 10, False), (2, 10, False), (3, 10, True), (3, 1, False),
])
def test_cpu_metric_with_measurement_uses_cpu_history_only(cpu_count, cpu_time, expected):
    hist = {'cases': {'a': {'avg_cpu_time': 1, 'cpu_run_count': cpu_count,
                            'avg_duration': 1, 'run_count': 10}}}
    assert (check_regression(hist, 'a', 10, cpu_time=cpu_time) is not None) == expected


def test_cpu_metric_message_marks_cpu_units():
    hist = {'cases': {'a': {'avg_cpu_time': 1, 'cpu_run_count': 3,
                            'avg_duration': 1, 'run_count': 10}}}
    msg = check_regression(hist, 'a', 10, cpu_time=2.5)
    assert msg is not None
    assert '2.50s CPU vs avg 1.00s CPU' in msg


def test_wall_metric_fallback_without_cpu_measurement():
    # Linux / 测量失败：cpu_time 缺失，退化为墙钟口径。
    hist = {'cases': {'a': {'avg_duration': 1, 'run_count': 3}}}
    assert check_regression(hist, 'a', 10) is not None


@pytest.mark.parametrize('measurements,expected', [([0.2, 0.3], 0.5), ([None, 0.3], None), ([0, 0], 0)])
def test_cpu_retry_sum_requires_complete_measurement(measurements, expected):
    facts = [ExecutionResult(return_code=rc, cpu_time=cpu) for rc, cpu in zip([1, 0], measurements)]
    with patch('symtest.core.orchestration.single.execute_command', side_effect=facts):
        result = execute_single_test_case(ExecutionSpec(command='cmd', retry_count=1),
                                          expectation={'return_code': 0})
    assert result['status'] == 'passed'
    assert result.get('cpu_time') == expected
    if expected is None:
        assert 'cpu_time_source' not in result


@pytest.mark.parametrize('measurements,expected', [([0.2, 0.3], 0.5), ([None, 0.3], None)])
def test_cpu_sequence_sum_requires_all_steps(measurements, expected):
    def execute(*args, **kwargs):
        cpu = measurements.pop(0)
        return {'status': 'passed', 'duration': 1, 'output': '', 'return_code': 0,
                **({'cpu_time': cpu} if cpu is not None else {})}
    result = execute_sequence('seq', [TestStep.from_flat(command='echo', args=[]) for _ in range(2)],
                              executor=execute)
    assert result.get('cpu_time') == expected


def test_cpu_resumed_sequence_does_not_report_partial_total(tmp_path):
    steps = [TestStep.from_flat(command='echo', args=[]) for _ in range(2)]
    calls = iter([('passed', 0), ('failed', 1), ('passed', 0)])
    def execute(*args, **kwargs):
        status, rc = next(calls)
        return {'status': status, 'return_code': rc, 'duration': 1, 'message': '',
                'output': 'cached', 'cpu_time': 0.3}
    first = execute_sequence('resume-cpu', steps, workspace=str(tmp_path),
                             resume=True, executor=execute)
    assert first['cpu_time'] == 0.6
    resumed = execute_sequence('resume-cpu', steps, workspace=str(tmp_path),
                               resume=True, executor=execute)
    assert resumed['status'] == 'passed'
    assert resumed['step_results'][0]['resumed'] is True
    assert 'cpu_time' not in resumed


@pytest.mark.parametrize('declared,peak,enabled,ready', [
    (False, None, True, False), (False, -1, True, False),
    (False, 100, True, True), (True, None, True, True),
    (False, None, False, True),
])
def test_timing_warmup_uses_pre_run_memory_information(declared, peak, enabled, ready):
    from symtest.core.test_case import TestCase
    runner = ParallelJSONRunner('unused.json')
    runner.test_cases = [TestCase('a', command='echo',
                                 resources={'min_memory_mb': 1} if declared else {})]
    runner._memory_enabled = enabled
    key = 'max_peak_memory_bytes' if os.name == 'nt' else 'max_peak_memory_bytes_linux'
    runner._memory_history = {'a': {key: peak}} if peak is not None else {}
    assert runner._timing_history_ready('a') is ready
