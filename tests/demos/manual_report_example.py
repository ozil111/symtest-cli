import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from symtest.runners.json_runner import JSONRunner
from symtest.utils.report_generator import ReportGenerator


def main():
    project_root = ROOT
    config_file = project_root / "tests" / "fixtures" / "test_cases.json"
    workspace = project_root

    runner = JSONRunner(config_file=str(config_file), workspace=str(workspace))
    success = runner.run_tests()

    report_path = project_root / "tests" / "test_report.txt"
    report_generator = ReportGenerator(runner.results, str(report_path))
    report_generator.print_report()
    report_generator.save_report()

    print(f"\n报告已保存到: {report_path}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

