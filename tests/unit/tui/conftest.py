"""Async fixtures for TUI run_test() tests."""

import pytest
from pathlib import Path
from unittest.mock import patch

from symtest.core.test_case import TestCase, TestCaseStep
from symtest.tui.controllers.case_controller import CaseController


@pytest.fixture
def sample_cases():
    """Return a list of sample TestCase objects for testing."""
    return [
        TestCase(name="echo_hello", command="echo", args=["hello"],
                 expected={"return_code": 0}, tags=["smoke"], description="A simple echo test"),
        TestCase(name="python_script", command="python", args=["-c", "print('hi')"],
                 expected={"output_contains": ["hi"]}, tags=["regression"], description=""),
        TestCase(
            name="multi_step",
            steps=[
                TestCaseStep(command="echo", args=["step1"], expected={"return_code": 0}),
                TestCaseStep(command="echo", args=["step2"], expected={"return_code": 0}),
            ],
            tags=["seq"], description="A sequence test case",
        ),
    ]


@pytest.fixture
def sample_config(tmp_path, sample_cases):
    """Create a temporary JSON config file with sample cases."""
    import json
    config = tmp_path / "cases.json"
    config_content = {
        "test_cases": [
            {
                "name": "echo_hello",
                "command": "echo",
                "args": ["hello"],
                "expected": {"return_code": 0},
                "tags": ["smoke"],
                "description": "A simple echo test",
            },
            {
                "name": "python_script",
                "command": "python",
                "args": ["-c", "print('hi')"],
                "expected": {"output_contains": ["hi"]},
                "tags": ["regression"],
                "description": "",
            },
            {
                "name": "multi_step",
                "steps": [
                    {"command": "echo", "args": ["step1"], "expected": {"return_code": 0}},
                    {"command": "echo", "args": ["step2"], "expected": {"return_code": 0}},
                ],
                "tags": ["seq"],
                "description": "A sequence test case",
            },
        ],
    }
    config.write_text(json.dumps(config_content), encoding="utf-8")
    return config


@pytest.fixture
def loaded_controller(sample_config):
    """Return a CaseController loaded with sample cases."""
    ctrl = CaseController()
    ctrl.load(str(sample_config))
    return ctrl
