import unittest

from app import app


class AccountPageTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_account_page_renders_mock_profile_and_activity(self):
        response = self.client.get("/account")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("My Account", body)
        self.assertIn("Manage your profile, skills, validations, and activity.", body)
        self.assertIn("Demo User", body)
        self.assertIn("Contributor", body)
        self.assertIn("demo@example.com", body)
        self.assertIn("NPV-DCF Analysis", body)
        self.assertIn("My Validation Results", body)
        self.assertIn("Account Settings", body)


if __name__ == "__main__":
    unittest.main()
