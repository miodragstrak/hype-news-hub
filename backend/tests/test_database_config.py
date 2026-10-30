import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.database.session import create_database_engine


class DatabaseConfigurationTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_missing_credentials_do_not_prevent_api_startup(self):
        from app.main import create_app
        config = Settings(_env_file=None)
        self.assertIsNotNone(create_app(config))
        with self.assertRaisesRegex(ValueError, "POSTGRES_PASSWORD"):
            create_database_engine(config)

    def test_password_characters_are_preserved_and_url_repr_is_redacted(self):
        password = "test-only:@/%? # password"
        config = Settings(_env_file=None, postgres_password=password)
        url = config.database_url
        self.assertEqual(make_url(url.render_as_string(hide_password=False)).password, password)
        self.assertNotIn(password, str(url))
        self.assertNotIn(password, repr(config))
        self.assertNotIn(password, config.model_dump_json())

    def test_environment_controls_private_database_and_tls(self):
        with patch.dict(os.environ, {
            "POSTGRES_HOST": "postgres", "POSTGRES_DB": "hype_news_hub",
            "POSTGRES_USER": "hype_news_hub", "POSTGRES_PASSWORD": "test-only",
            "POSTGRES_SSLMODE": "verify-full", "POSTGRES_CONNECT_TIMEOUT_SECONDS": "7",
        }):
            url = Settings(_env_file=None).database_url
        self.assertEqual((url.host, url.database, url.username), ("postgres", "hype_news_hub", "hype_news_hub"))
        self.assertEqual(url.query, {"sslmode": "verify-full", "connect_timeout": "7"})

    def test_engine_creation_is_lazy_and_pool_is_bounded(self):
        config = Settings(_env_file=None, postgres_host="unreachable.invalid", postgres_password="test-only",
                          database_pool_size=2, database_max_overflow=1)
        engine = create_database_engine(config)
        self.addCleanup(engine.dispose)
        self.assertEqual(engine.pool.checkedout(), 0)
        self.assertEqual(engine.pool.size(), 2)
        self.assertTrue(engine.hide_parameters)

    def test_invalid_connection_settings_fail_validation(self):
        for settings in [{"postgres_port": 0}, {"postgres_port": 65536}, {"database_pool_size": 0},
                         {"database_max_overflow": -1}, {"database_pool_timeout_seconds": 0},
                         {"postgres_connect_timeout_seconds": 0}, {"postgres_sslmode": "unsafe-typo"}]:
            with self.subTest(settings=settings), self.assertRaises(ValidationError):
                Settings(_env_file=None, **settings)
