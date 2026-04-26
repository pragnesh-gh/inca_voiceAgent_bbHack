import os
import unittest

from fastapi.testclient import TestClient

from inca_voice.policy_lookup import find_policyholder_in_text, lookup_policyholder
from inca_voice.twilio_app import app


DB_PATH = os.path.join(os.getcwd(), "data", "mock_policyholders.csv")


class PolicyLookupTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_matches_pragnesh_by_name_and_date_of_birth(self):
        result = find_policyholder_in_text(
            DB_PATH,
            "My name is Pragnesh Kumar Pallaprolu and my date of birth is 26th of October 2001.",
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["policyholder"]["policy_number"], "MM-KFZ-4831")
        self.assertEqual(result["policyholder"]["date_of_birth"], "2001-10-26")

    def test_matches_month_first_birth_date_with_filler_words(self):
        result = find_policyholder_in_text(
            DB_PATH,
            "My name is Pragnesh and I'm born, um, October 26th, 2001.",
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["policyholder"]["policy_number"], "MM-KFZ-4831")

    def test_lookup_by_license_plate(self):
        result = lookup_policyholder(DB_PATH, license_plate="B-AM-1184")

        self.assertTrue(result["matched"])
        self.assertEqual(result["policyholder"]["full_name"], "Anna Mueller")

    def test_matches_markus_schneider_demo_persona_by_plate(self):
        result = lookup_policyholder(DB_PATH, license_plate="B-MS-4721")

        self.assertTrue(result["matched"])
        self.assertEqual(result["policyholder"]["full_name"], "Markus Schneider")
        self.assertEqual(result["policyholder"]["policy_number"], "MM-KFZ-2197")

    def test_endpoint_requires_token_when_configured(self):
        os.environ["POLICY_LOOKUP_TOOL_TOKEN"] = "lookup-secret"
        os.environ["POLICYHOLDER_DB_PATH"] = DB_PATH
        client = TestClient(app)

        denied = client.post("/tools/lookup-policyholder", json={"policy_number": "MM-KFZ-4831"})
        allowed = client.post(
            "/tools/lookup-policyholder",
            headers={"X-Tool-Token": "lookup-secret"},
            json={"policy_number": "MM-KFZ-4831"},
        )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.json()["matched"])


if __name__ == "__main__":
    unittest.main()
