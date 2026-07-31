# Example usage
from symtest.runners.parallel_json_runner import ParallelJSONRunner
from symtest.utils.report_generator import ReportGenerator
from symtest.logging_config import setup_console_logging
import argparse
import sys
import os

def main():
    parser = argparse.ArgumentParser(description="Fatigue test runner")
    parser.add_argument("--test-target", nargs="+", default=None,
                        help="指定要运行的测试案例名称，支持多个，例如: --test-target alpha gamma")
    parser.add_argument("--tag", nargs="+", default=None, dest="test_tag",
                        help="按标签过滤测试案例，支持多个(OR关系)，例如: --tag smoke --tag regression")
    args = parser.parse_args()

    setup_console_logging()

    runner = ParallelJSONRunner(
        config_file="test_cases.json",
        workspace=os.path.dirname(os.path.abspath(__file__)),
        max_workers=4, execution_mode="thread",
        history_dir="./hist",
        test_case_filter=args.test_target,
        test_case_tag_filter=args.test_tag
    )
    success = runner.run_tests()
    
    # Generate and save the report
    report_generator = ReportGenerator(runner.results, os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_report.txt"))
    report_generator.save_report()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()