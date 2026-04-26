import os
from collections import Counter
import unittest

from fastapi.testclient import TestClient

from inca_voice.policy_lookup import find_policyholder_in_text, load_policyholders, lookup_policyholder
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
        self.assertEqual(result["policyholder"]["occupation"], "Master's student")
        self.assertEqual(result["policyholder"]["university"], "Bielefeld University")
        self.assertEqual(result["policyholder"]["nationality"], "India")
        self.assertEqual(result["policyholder"]["eu_status"], "Non-EU citizen")
        self.assertEqual(result["policyholder"]["residence_permit_valid_until"], "2027-02-27")

    def test_matches_month_first_birth_date_with_filler_words(self):
        result = find_policyholder_in_text(
            DB_PATH,
            "My name is Pragnesh and I'm born, um, October 26th, 2001.",
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["policyholder"]["policy_number"], "MM-KFZ-4831")

    def test_matches_pragnesh_asr_aliases_with_date_of_birth(self):
        for heard_name in ("Pratnesh", "Pregnesh", "Pragnish"):
            with self.subTest(heard_name=heard_name):
                result = find_policyholder_in_text(
                    DB_PATH,
                    f"I am {heard_name}. My date of birth is 26th October, 2001.",
                )

                self.assertTrue(result["matched"])
                self.assertEqual(result["policyholder"]["full_name"], "Pragnesh Kumar Pallaprolu")
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

    def test_matches_new_demo_personas_by_phone_plate_and_name_dob(self):
        by_phone = lookup_policyholder(DB_PATH, phone="+491631440882")
        by_plate = lookup_policyholder(DB_PATH, license_plate="B-ER-4408")
        by_name_dob = find_policyholder_in_text(
            DB_PATH,
            "Ich bin Erika Richter, geboren am 8. April 1944.",
        )

        self.assertTrue(by_phone["matched"])
        self.assertEqual(by_phone["policyholder"]["policy_number"], "MM-KFZ-4408")
        self.assertTrue(by_plate["matched"])
        self.assertEqual(by_plate["policyholder"]["full_name"], "Erika Richter")
        self.assertTrue(by_name_dob["matched"])
        self.assertEqual(by_name_dob["policyholder"]["license_plate"], "B-ER-4408")

    def test_does_not_verify_on_date_of_birth_alone(self):
        result = lookup_policyholder(DB_PATH, date_of_birth="1978-03-14")

        self.assertFalse(result["matched"])

    def test_mock_policyholders_have_distinct_core_identifiers(self):
        records = load_policyholders(DB_PATH)
        fields = ["policy_number", "date_of_birth", "phone", "license_plate", "vin"]

        for field in fields:
            values = [record[field] for record in records if record.get(field)]
            duplicates = [value for value, count in Counter(values).items() if count > 1]
            self.assertEqual(duplicates, [], f"Duplicate {field}: {duplicates}")

    def test_prefers_explicit_name_over_generic_i_am_phrase(self):
        result = find_policyholder_in_text(
            DB_PATH,
            (
                "Um, I am here to have an accident incident to claim. "
                "My name is Mark Schneider. Uh, date of birth is 14th March, 1978."
            ),
        )

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
