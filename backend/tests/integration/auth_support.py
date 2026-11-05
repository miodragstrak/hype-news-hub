"""Revisions 07/08 fixtures: only explicitly empty disposable test databases are ever cleaned."""
from alembic import command
from sqlalchemy import text

from app.models.auth import AuthBase
from tests.integration.test_persistent_collection import PersistentCollectionCase
from tests.integration.test_postgresql import alembic_config


class AuthDatabaseCase(PersistentCollectionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.engine.begin() as connection:
            config = alembic_config(connection, include_auth=True)
            command.upgrade(config, "20261104_08")
        cls.addClassCleanup(cls.remove_auth_test_schema)

    @classmethod
    def remove_auth_test_schema(cls):
        # Production downgrade is forbidden. Test-only cleanup follows the parent
        # fixture's initially-empty, exact-name hype_news_hub_test assertion.
        with cls.engine.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")) == "hype_news_hub_test"
            AuthBase.metadata.drop_all(connection)
            connection.execute(text("DROP FUNCTION IF EXISTS public.hwn_security_event_immutable()"))
            command.stamp(alembic_config(connection, include_auth=True), "20261101_06")

    def tearDown(self):
        from app.database.base import Base
        with self.engine.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")) == "hype_news_hub_test"
            tables = list(Base.metadata.sorted_tables) + list(AuthBase.metadata.sorted_tables)
            connection.execute(text("TRUNCATE TABLE " + ", ".join("public." + t.name for t in tables) + " CASCADE"))
        super().tearDown()
