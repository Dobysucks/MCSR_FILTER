from __future__ import annotations

import tempfile
import threading
import unittest
import logging
import subprocess
from pathlib import Path

from mcsr_filter.cache import MAX_SEED, MIN_SEED, SeedCache, parse_seed
from mcsr_filter.config import AppConfig
from mcsr_filter.generator import CandidateStream, GenerationController, extract_structure_labels
from mcsr_filter.logging_setup import configure_logging
from mcsr_filter.engine import UnavailableMinecraft262Provider
from mcsr_filter.engine import MCSeedFinderProvider


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db, self.txt = root / "cache.db", root / "seeds.txt"

    def tearDown(self):
        logger = logging.getLogger("mcsr_filter")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        self.tmp.cleanup()

    def cache(self):
        return SeedCache(self.db, self.txt, "26.2", "test-filter")

    def test_signed_range_and_invalid_values(self):
        self.assertEqual(parse_seed(str(MIN_SEED)), str(MIN_SEED))
        self.assertEqual(parse_seed(str(MAX_SEED)), str(MAX_SEED))
        with self.assertRaises(ValueError):
            parse_seed(str(MAX_SEED + 1))

    def test_import_export_recovery_and_duplicates(self):
        self.txt.write_text("1\n1\n-2\ninvalid\n", encoding="utf-8")
        cache = self.cache()
        self.assertEqual(cache.seeds(), ["1", "-2"])
        cache.close()
        self.db.unlink()
        cache = self.cache()
        self.assertEqual(cache.seeds(), ["1", "-2"])
        cache.close()
        self.txt.unlink()
        cache = self.cache()
        self.assertEqual(self.txt.read_text(encoding="utf-8").splitlines()[-2:], ["SEED: 1", "SEED: -2"])
        cache.close()

    def test_structured_export_and_labels(self):
        cache = self.cache()
        cache.insert("1", ("village", "ruined portal"))
        cache.export()
        text = self.txt.read_text(encoding="utf-8")
        self.assertIn("Generated count: 1", text)
        self.assertIn("SEED: 1 (village, ruined portal)", text)
        self.assertEqual(cache.entries(), [("1", ["village", "ruined portal"])])
        cache.close()

    def test_backend_structure_labels_are_report_derived(self):
        report = {"filter": {"children": [{"condition": "structure_near", "matched": True, "hits": [{"name": "desert_pyramid"}]}, {"condition": "structure_near", "matched": True, "hits": [{"name": "bastion_remnant"}]}]}}
        self.assertEqual(extract_structure_labels(report), ("desert temple", "bastion"))

    def test_unreported_structure_is_not_labeled(self):
        report = {"filter": {"children": [{"condition": "structure_near", "matched": True, "any_of": ["village"]}]}}
        self.assertEqual(extract_structure_labels(report), ())

    def test_unique_and_concurrent_insert(self):
        cache = self.cache()
        results = []
        def insert():
            results.append(cache.insert("42"))
        threads = [threading.Thread(target=insert) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(results), 1)
        self.assertEqual(cache.count(), 1)
        cache.close()

    def test_repeated_runs_never_duplicate(self):
        cache = self.cache()
        first = ["1", "2", "3"]
        second = ["3", "4", "5"]
        cache.insert_many(first)
        cache.insert_many(second)
        self.assertEqual(cache.seeds(), ["1", "2", "3", "4", "5"])
        self.assertEqual(cache.count(), 5)
        cache.close()

    def test_version_rejected(self):
        with self.assertRaises(ValueError):
            AppConfig(minecraft_version="1.16.1").validate()
        self.assertEqual(AppConfig().filter_version, "MCSR-26.2-ADAPTED-v2")

    def test_provider_fails_closed_without_verified_backend(self):
        provider = UnavailableMinecraft262Provider()
        result = provider.self_test()
        self.assertFalse(result.verified)
        with self.assertRaises(RuntimeError):
            provider.accepts(0, AppConfig().filters)

    def test_backend_check_exit_one_is_a_valid_non_match(self):
        provider = MCSeedFinderProvider(Path("mcseed-finder.exe"))
        provider._verified = True
        result = {
            "version": "26.2",
            "seed": 0,
            "matched": False,
        }
        provider._run = lambda *args: subprocess.CompletedProcess(
            args, 1, stdout='{"version":"26.2","seed":0,"matched":false}\n', stderr=""
        )
        self.assertEqual(provider._check(0, "overworld", AppConfig().filters), result)

    def test_candidate_stream_is_deterministic_and_signed(self):
        first = CandidateStream(7)
        second = CandidateStream(7)
        values_a = [first.next() for _ in range(20)]
        values_b = [second.next() for _ in range(20)]
        self.assertEqual(values_a, values_b)
        self.assertTrue(all(MIN_SEED <= value <= MAX_SEED for value in values_a))

    def test_controller_generates_new_seeds_across_runs(self):
        class TestProvider:
            version = "test"

            def accepts(self, seed, filters, pool="overworld"):
                return seed == seed

        config = AppConfig(target_seeds=10, workers=2, master_rng_seed=12)
        logger = configure_logging(Path(self.tmp.name) / "generation.log")
        cache = self.cache()
        first = GenerationController(config, cache, TestProvider(), Path(self.tmp.name) / "state.json", logger).run()
        first_seeds = set(cache.seeds())
        self.assertEqual(first.found, 10)
        config.master_rng_seed = 13
        second = GenerationController(config, cache, TestProvider(), Path(self.tmp.name) / "state.json", logger).run()
        second_seeds = set(cache.seeds()) - first_seeds
        self.assertEqual(second.found, 10)
        self.assertEqual(len(second_seeds), 10)
        self.assertEqual(cache.count(), 20)
        cache.close()

    def test_pause_and_resume(self):
        import time

        class SlowProvider:
            version = "test"

            def accepts(self, seed, filters, pool="overworld"):
                time.sleep(0.002)
                return seed == seed

        config = AppConfig(target_seeds=100, workers=1, master_rng_seed=1)
        cache = self.cache()
        controller = GenerationController(config, cache, SlowProvider(), Path(self.tmp.name) / "state.json", configure_logging(Path(self.tmp.name) / "pause.log"))
        thread = threading.Thread(target=controller.run)
        thread.start()
        time.sleep(0.02)
        controller.pause()
        time.sleep(0.03)
        self.assertTrue(thread.is_alive())
        paused_count = cache.count()
        self.assertLess(paused_count, 100)
        controller.resume()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(cache.count(), 100)
        cache.close()


if __name__ == "__main__":
    unittest.main()
