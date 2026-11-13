"""Focused checks for the shared-pool merge and its allocator.

Run with: python -m pytest tests/test_merge.py  (or python -m unittest).
These use an isolated SQLite database and the FastAPI TestClient; they do not
exercise Redis, MySQL or the container stack.
"""
import itertools
import math
import os
import sys
import tempfile
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from src.services.allocation import allocate, uncovered


def brute_force(uppers, people, suggestions, capacity):
    """Exact reference: minimise max uncovered, tie-break on earlier venues."""
    best = None
    for combo in itertools.product(*[range(2, ceiling + 1) for ceiling in suggestions]):
        if sum(combo) > capacity:
            continue
        score = max(uncovered(upper, carry, guides)
            for upper, carry, guides in zip(uppers, people, combo))
        key = (score, tuple(-value for value in combo))
        if best is None or key < best[0]:
            best = (key, combo)
    return None if best is None else best[1]


class AllocateTest(unittest.TestCase):
    def test_matches_exact_optimum_on_small_grids(self):
        for uppers in itertools.product([0, 3, 7, 12, 19, 25], repeat=2):
            for people in itertools.product([2, 3, 5, 8], repeat=2):
                suggestions = [max(2, math.ceil(upper / carry)) for upper, carry in zip(uppers, people)]
                for capacity in range(4, sum(suggestions) + 2):
                    expected = brute_force(uppers, people, suggestions, capacity)
                    got = allocate(uppers, people, suggestions, capacity)
                    self.assertEqual(got, list(expected),
                        (uppers, people, suggestions, capacity))

    def test_three_venue_random_cases_match_exact_optimum(self):
        import random
        rng = random.Random(261104)
        for _ in range(300):
            people = [rng.choice([2, 3, 5, 8, 10]) for _ in range(3)]
            uppers = [round(rng.randint(0, 260) / 10, 1) for _ in range(3)]
            suggestions = [max(2, math.ceil(upper / carry)) for upper, carry in zip(uppers, people)]
            if sum(suggestions) > 24:
                continue
            capacity = rng.randint(6, sum(suggestions) + 3)
            expected = brute_force(uppers, people, suggestions, capacity)
            self.assertEqual(allocate(uppers, people, suggestions, capacity), list(expected),
                (uppers, people, suggestions, capacity))

    def test_never_exceeds_capacity_floor_or_suggestion(self):
        for uppers, people, suggestions, capacity in [
            ([300, 300, 300], [50, 50, 50], [6, 6, 6], 10),
            ([1000, 10], [10, 100], [100, 2], 7),
            ([0, 0, 0], [65, 65, 65], [2, 2, 2], 6),
        ]:
            result = allocate(uppers, people, suggestions, capacity)
            self.assertEqual(len(result), len(uppers))
            self.assertTrue(all(guides >= 2 for guides in result))
            self.assertLessEqual(sum(result), capacity)
            self.assertTrue(all(guides <= ceiling for guides, ceiling in zip(result, suggestions)))

    def test_balances_the_worst_shortfall_instead_of_filling_one_venue(self):
        # 7+5 leaves 75 people uncovered at the worse venue; 6+6 leaves 110.
        self.assertEqual(allocate([500, 300], [65, 45], [8, 7], 12), [7, 5])

    def test_rejects_capacity_below_the_two_per_venue_floor(self):
        with self.assertRaises(ValueError):
            allocate([100, 100, 100], [65, 45, 55], [2, 2, 2], 5)
        with self.assertRaises(ValueError):
            allocate([100, 100], [65, 45], [2, 2], 3)

    def test_rejects_suggestion_below_floor(self):
        with self.assertRaises(ValueError):
            allocate([100, 100], [65, 45], [1, 2], 10)

    def test_zero_upper_still_gets_the_floor_without_idle(self):
        # Nothing is uncovered, so spare capacity is not handed out.
        self.assertEqual(allocate([0, 0], [65, 45], [2, 2], 6), [2, 2])
        self.assertEqual(allocate([0, 0], [65, 45], [2, 2], 9), [2, 2])


class MergeEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(cls.tmp, "merge.sqlite3")
        os.environ["SEED_DEMO"] = "true"
        from fastapi.testclient import TestClient
        from src.main import app
        cls.client = TestClient(app)
        cls.client.__enter__()
        token = cls.client.post("/auth/login",
            json={"email": "analyst@stage.local", "password": "Stage2611!"}).json()["access_token"]
        cls.headers = {"Authorization": "Bearer " + token}
        cls.plans = cls.client.get("/plans", headers=cls.headers).json()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def plan_for(self, venue):
        return next(plan for plan in self.plans if plan["venue"] == venue)

    def post(self, **body):
        return self.client.post("/merges", json=body, headers=self.headers)

    def test_three_venues_merge_and_reconcile(self):
        response = self.post(name="三厅共用编排", plan_ids=[plan["id"] for plan in self.plans],
            daily_capacity=12)
        self.assertEqual(response.status_code, 201)
        roster = response.json()
        self.assertEqual(roster["venues"], ["大剧场", "黑匣子", "实验厅"])
        self.assertTrue(roster["reconciled"])
        self.assertEqual(roster["totals"]["allocated"] + roster["totals"]["gap"], roster["totals"]["demand"])
        self.assertEqual(roster["totals"]["allocated"] + roster["totals"]["unused"],
            12 * len(roster["days"]))
        for day in roster["days"]:
            self.assertLessEqual(day["allocated"], 12)
            self.assertEqual(day["allocated"], sum(row["allocated"] for row in day["venues"]))
            for row in day["venues"]:
                self.assertGreaterEqual(row["allocated"], 2)
                self.assertLessEqual(row["allocated"], row["demand"])

    def test_daily_capacity_below_floor_is_rejected(self):
        response = self.post(name="容量不足编排", plan_ids=[plan["id"] for plan in self.plans],
            daily_capacity=5)
        self.assertEqual(response.status_code, 422)
        self.assertIn("保底", response.json()["detail"])

    def test_duplicate_venue_is_rejected(self):
        first = self.plan_for("大剧场")
        response = self.post(name="重复场馆编排", plan_ids=[first["id"], first["id"]], daily_capacity=12)
        self.assertEqual(response.status_code, 422)

    def test_mismatched_date_range_is_rejected(self):
        from src.utils.database import get_row, update_row
        trimmed = self.plan_for("实验厅")
        days = get_row("plans", trimmed["id"])["days"]
        update_row("plans", trimmed["id"], {"days": days[:-1]})
        try:
            response = self.post(name="区间不齐编排", plan_ids=[plan["id"] for plan in self.plans],
                daily_capacity=12)
            self.assertEqual(response.status_code, 422)
            self.assertIn("日期范围", response.json()["detail"])
        finally:
            update_row("plans", trimmed["id"], {"days": days})

    def test_original_plans_are_untouched(self):
        before = {plan["id"]: plan for plan in self.client.get("/plans", headers=self.headers).json()}
        self.post(name="不动原编排", plan_ids=[plan["id"] for plan in self.plans], daily_capacity=12)
        after = {plan["id"]: plan for plan in self.client.get("/plans", headers=self.headers).json()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
