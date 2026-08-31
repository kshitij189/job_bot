import unittest

from app import Candidate, render


class RenderTests(unittest.TestCase):
    def test_renders_links_and_only_available_emails(self) -> None:
        candidate = Candidate(
            "Acme", "Asha Patel", "CTO", "https://www.linkedin.com/in/asha-patel",
            "Authorized source", 1.0, True, "asha@acme.example", "asha@example.net",
        )

        message = render("Acme", "startup", [candidate])

        self.assertIn("LinkedIn: https://www.linkedin.com/in/asha-patel", message)
        self.assertIn("Work email: asha@acme.example", message)
        self.assertIn("Personal email: asha@example.net", message)

    def test_omits_unavailable_emails(self) -> None:
        candidate = Candidate("Acme", "Asha Patel", "CTO", "https://linkedin.example/asha", "Source", 1.0, True)

        message = render("Acme", "startup", [candidate])

        self.assertNotIn("email:", message.casefold())


if __name__ == "__main__":
    unittest.main()
