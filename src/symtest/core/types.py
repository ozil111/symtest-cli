from typing import Any, Dict, List, Optional, TypedDict


class ExpectedResult(TypedDict, total=False):
    """Expectation configuration for a single test case."""

    return_code: Optional[int]
    output_contains: List[str]
    output_matches: Optional[str]
    compare_files: List[Dict[str, Any]]
    """List of file comparison specs.
    Each spec is a dict with:
        actual   (str): path to the file produced by the test command
        baseline (str): path to the golden/reference file
        type     (str, optional): comparator type (e.g. 'h5','json','csv','xml','text','binary')
                                  auto-detected from extension if omitted
        Additional kwargs are forwarded to the comparator (e.g. rtol, atol, encoding, ...)
    """


class ResourceRequirements(TypedDict, total=False):
    """Optional resource hints for scheduling."""

    estimated_time: float  # seconds, used for ordering (LPT)
    min_memory_mb: float  # soft hint to avoid OOM
    priority: int  # higher value => higher priority
    cpu_cores: int  # number of CPU cores required by this task


class TestCaseData(TypedDict, total=False):
    """Input data shape for a test case after解析/路径处理."""

    name: str
    command: str
    args: List[str]
    expected: ExpectedResult
    description: Optional[str]
    timeout: Optional[float]
    resources: Optional[ResourceRequirements]
    retry_count: int
    expected_failure: bool
    xfail_reason: Optional[str]
    xfail_quiet: bool


class SetupConfig(TypedDict):
    """Setup configuration (currently environment variables only)."""

    environment_variables: Dict[str, str]


class TestSuiteConfig(TypedDict):
    """Top-level configuration for a suite loaded from JSON/YAML."""

    setup: Optional[SetupConfig]
    test_cases: List[TestCaseData]


class TestResultData(TypedDict):
    """Normalized result produced by executing a single test case."""

    name: str
    status: str  # 'passed', 'failed', 'timeout'
    message: str
    command: str
    output: str
    return_code: Optional[int]
    duration: float
    # ── New fields (optional, backward-compatible) ──
    expected: Optional[Dict[str, Any]]
    description: Optional[str]
    tags: List[str]
    failure_kind: Optional[str]  # 'return_code' | 'output_contains' | 'output_matches' | 'file_compare' | 'timeout' | 'execution_error'
    attempts: int
    flaky: bool
    attempt_history: List[Dict[str, Any]]
    step_results: List[Dict[str, Any]]
    compare_failures: List[Dict[str, Any]]
    baseline_updated: List[str]
    failed_step: Optional[int]
    # ── Structured output channels (split from combined ``output``) ──
    stdout: str
    stderr: str
    # ── Per-assertion pass/fail detail (populated on both pass and failure) ──
    assertion_results: List[Dict[str, Any]]
    xfail_reason: Optional[str]
    # ── Structured remediation suggestion (populated on failure) ──
    # Dict with: action ('update_baseline' | 'update_expected' | 'increase_timeout'
    # | 'investigate'), command (concrete symtest command, filled by runners),
    # reason (human/AI-readable explanation).
    next_action_hint: Optional[Dict[str, Any]]

