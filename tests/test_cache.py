import unittest
import tempfile
import shutil
import time
from src.cache import GithubCache


class TestGithubCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = GithubCache(self.dir, ttl_seconds=60)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_miss_then_hit(self):
        self.assertIsNone(self.cache.get("octocat"))
        self.cache.set("octocat", {"login": "octocat"})
        self.assertEqual(self.cache.get("octocat")["login"], "octocat")

    def test_expiry(self):
        short_cache = GithubCache(self.dir, ttl_seconds=0)
        short_cache.set("expiring", {"login": "expiring"})
        time.sleep(0.05)
        self.assertIsNone(short_cache.get("expiring"))

    def test_username_sanitized_for_filename(self):
        self.cache.set("weird/../name", {"login": "x"})
        self.assertEqual(self.cache.get("weird/../name")["login"], "x")

    def test_corrupt_cache_file_treated_as_miss(self):
        path = self.cache._path_for("broken")
        with open(path, "w") as fh:
            fh.write("not valid json{{{")
        self.assertIsNone(self.cache.get("broken"))


if __name__ == "__main__":
    unittest.main()
