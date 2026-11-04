import secrets
import unittest
from unittest.mock import patch, Mock

from argon2 import PasswordHasher

from app.bootstrap_admin import interactive_bootstrap
from app.core.config import Settings
from app.selfhosted import create_selfhosted_app
from app.services.authentication import email_address, password_hash
from tests.test_selfhosted import selfhosted_settings


class ApplicationAuthenticationUnitTests(unittest.TestCase):
    def test_normalized_email_and_invalid_boundaries(self):
        self.assertEqual(email_address("  EDITOR+News@Example.COM  "), "editor+news@example.com")
        for value in ["a@-bad.invalid", "a@bad..invalid", ".a@example.invalid", "a..b@example.invalid",
                      "x"*65+"@example.invalid", "č@example.invalid", "no email", "a@example.invalid\nextra"]:
            with self.subTest(value=value), self.assertRaises(ValueError):email_address(value)

    def test_argon2id_and_exact_password_semantics(self):
        value=" " + secrets.token_urlsafe(24) + " "
        encoded=password_hash(value)
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertTrue(PasswordHasher().verify(encoded,value))
        for invalid in [secrets.token_urlsafe(5), "a"*129, "\ud800"*15]:
            with self.assertRaises((ValueError,UnicodeError)):password_hash(invalid)

    def test_initial_admin_cli_rejects_noninteractive_input_and_mismatched_confirmation(self):
        with patch("app.bootstrap_admin.sys.stdin", Mock(isatty=lambda:False)), patch("app.bootstrap_admin.getpass.getpass") as prompt:
            with self.assertRaisesRegex(ValueError,"interactive"):interactive_bootstrap(Settings(_env_file=None))
            prompt.assert_not_called()
        with patch("app.bootstrap_admin.sys.stdin", Mock(isatty=lambda:True)), patch("builtins.input",return_value="admin@example.invalid"), \
             patch("app.bootstrap_admin.getpass.getpass",side_effect=[secrets.token_urlsafe(24),secrets.token_urlsafe(24)]), patch("app.bootstrap_admin.bootstrap_admin") as create:
            with self.assertRaisesRegex(ValueError,"match"):interactive_bootstrap(Settings(_env_file=None))
            create.assert_not_called()

    def test_incomplete_auth_security_configuration_cannot_activate_application(self):
        for proxies in ["", "*", "0.0.0.0/0", "::/0", "not-an-address"]:
            with self.subTest(proxies=proxies), self.assertRaises(ValueError):
                create_selfhosted_app(selfhosted_settings(auth_enabled=True,auth_trusted_proxy_ips=proxies))
