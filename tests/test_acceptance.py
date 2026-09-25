from dataclasses import FrozenInstanceError
import unittest

from ade.acceptance import AcceptanceReport, CheckResult, build_report


class AcceptanceTests(unittest.TestCase):
    def test_check_result_valid(self):
        result = CheckResult(name="check_1", passed=True, detail="all good")
        self.assertEqual(result.name, "check_1")
        self.assertTrue(result.passed)
        self.assertEqual(result.detail, "all good")

    def test_check_result_default_detail(self):
        result = CheckResult(name="check_1", passed=False)
        self.assertEqual(result.detail, "")

    def test_check_result_validation(self):
        with self.assertRaises(ValueError):
            CheckResult(name="", passed=True)
        with self.assertRaises(ValueError):
            CheckResult(name="   ", passed=True)

    def test_check_result_immutability(self):
        result = CheckResult(name="check_1", passed=True)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            result.passed = False  # type: ignore[misc]

    def test_acceptance_report_empty(self):
        report = AcceptanceReport()
        self.assertEqual(report.total, 0)
        self.assertEqual(report.passed_count, 0)
        self.assertEqual(report.failed_count, 0)
        self.assertFalse(report.complete)

    def test_acceptance_report_immutability(self):
        report = AcceptanceReport()
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            report.results = ()  # type: ignore[misc]

    def test_acceptance_report_all_passed(self):
        r1 = CheckResult(name="check_1", passed=True)
        r2 = CheckResult(name="check_2", passed=True, detail="ok")
        report = AcceptanceReport(results=(r1, r2))

        self.assertEqual(report.total, 2)
        self.assertEqual(report.passed_count, 2)
        self.assertEqual(report.failed_count, 0)
        self.assertTrue(report.complete)

    def test_acceptance_report_mixed_results(self):
        r1 = CheckResult(name="check_1", passed=True)
        r2 = CheckResult(name="check_2", passed=False, detail="failed assertion")
        r3 = CheckResult(name="check_3", passed=True)
        report = AcceptanceReport(results=(r1, r2, r3))

        self.assertEqual(report.total, 3)
        self.assertEqual(report.passed_count, 2)
        self.assertEqual(report.failed_count, 1)
        self.assertFalse(report.complete)

    def test_acceptance_report_all_failed(self):
        r1 = CheckResult(name="check_1", passed=False)
        r2 = CheckResult(name="check_2", passed=False)
        report = AcceptanceReport(results=(r1, r2))

        self.assertEqual(report.total, 2)
        self.assertEqual(report.passed_count, 0)
        self.assertEqual(report.failed_count, 2)
        self.assertFalse(report.complete)

    def test_build_report_helper(self):
        r1 = CheckResult(name="c1", passed=True)
        r2 = CheckResult(name="c2", passed=True)

        # List iterable
        report_from_list = build_report([r1, r2])
        self.assertEqual(report_from_list.results, (r1, r2))
        self.assertTrue(report_from_list.complete)

        # Generator iterable
        report_from_gen = build_report(r for r in [r1, r2])
        self.assertEqual(report_from_gen.results, (r1, r2))
        self.assertTrue(report_from_gen.complete)


if __name__ == "__main__":
    unittest.main()
