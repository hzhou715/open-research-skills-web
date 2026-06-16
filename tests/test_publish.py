import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import app as app_module


class PublishSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_data_dir = app_module.DATA_DIR
        self.original_index = app_module.SUBMITTED_SKILLS_INDEX
        self.original_upload_dir = app_module.SUBMITTED_SKILLS_UPLOAD_DIR
        tmp_path = Path(self.tmp.name)
        app_module.DATA_DIR = tmp_path / "data"
        app_module.SUBMITTED_SKILLS_INDEX = app_module.DATA_DIR / "submitted_skills.json"
        app_module.SUBMITTED_SKILLS_UPLOAD_DIR = tmp_path / "uploads" / "submitted_skills"
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.DATA_DIR = self.original_data_dir
        app_module.SUBMITTED_SKILLS_INDEX = self.original_index
        app_module.SUBMITTED_SKILLS_UPLOAD_DIR = self.original_upload_dir
        self.tmp.cleanup()

    def test_publish_requires_skill_name_description_and_skill_md(self):
        response = self.client.post("/publish", data={}, content_type="multipart/form-data")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Skill Name is required.", body)
        self.assertIn("Short Description is required.", body)
        self.assertIn("SKILL.md upload is required.", body)

    def test_publish_saves_metadata_files_and_confirmation(self):
        response = self.client.post(
            "/publish",
            data={
                "name": "Reusable Coding Skill",
                "description": "Codes research documents.",
                "author": "Researcher",
                "institution": "Open University",
                "contact_email": "researcher@example.com",
                "research_type": "Qualitative Analysis",
                "purpose": "Extract evidence.",
                "required_inputs": "Documents",
                "expected_outputs": "Coding table",
                "procedure_summary": "Read and code.",
                "decision_rules": "Use the codebook.",
                "validation_standard": "Compare with benchmark coding.",
                "known_limitations": "Draft workflow.",
                "skill_status": "Draft",
                "visibility": "Private Draft",
                "skill_md": (BytesIO(b"# Skill"), "SKILL.md"),
                "sample_input_files": (BytesIO(b"input"), "sample.txt"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/publish/confirmation/reusable-coding-skill", response.headers["Location"])

        saved = app_module.load_submitted_skills()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "Reusable Coding Skill")
        self.assertEqual(saved[0]["research_type"], "Qualitative Analysis")
        self.assertTrue((app_module.SUBMITTED_SKILLS_UPLOAD_DIR / "reusable-coding-skill" / "SKILL.md").exists())
        self.assertTrue((app_module.SUBMITTED_SKILLS_UPLOAD_DIR / "reusable-coding-skill" / "sample.txt").exists())

        confirmation = self.client.get(response.headers["Location"])
        body = confirmation.get_data(as_text=True)
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("Your skill has been submitted successfully.", body)
        self.assertIn("Reusable Coding Skill", body)
        self.assertIn("SKILL.md", body)


if __name__ == "__main__":
    unittest.main()
