from eventsourcing.application.base import ApplicationWithEventStores
from eventsourcing.infrastructure.sqlalchemy.datastore import SQLAlchemySettings, SQLAlchemyDatastore
from eventsourcing.infrastructure.sqlalchemy.activerecords import IntegerSequencedItemRecord


class TodoApp(ApplicationWithEventStores):
    def __init__(self, session):
        # Construct event stores and persistence policies.
        datastore = SQLAlchemyDatastore(
            settings=SQLAlchemySettings(uri='sqlite:///:memory:'),
            tables=(IntegerSequencedItemRecord,),
        )

        datastore.setup_connection()
        datastore.setup_tables()

        super(TodoApp, self).__init__()
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self
