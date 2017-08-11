from uuid import uuid4, uuid5

from eventsourcing.application.base import ApplicationWithPersistencePolicies
from eventsourcing.domain.model.aggregate import AggregateRoot
from eventsourcing.domain.model.collection import Collection, register_new_collection
from eventsourcing.domain.model.decorators import mutator
from eventsourcing.domain.model.entity import mutate_entity
from eventsourcing.domain.model.events import publish, subscribe, unsubscribe
from eventsourcing.infrastructure.eventstore import AbstractEventStore
from eventsourcing.infrastructure.repositories.collection_repo import CollectionRepository
from eventsourcing.infrastructure.sqlalchemy.activerecords import IntegerSequencedItemRecord, \
    SQLAlchemyActiveRecordStrategy


class TodoList(AggregateRoot):
    def __init__(self, user_id, **kwargs):
        super(TodoList, self).__init__(**kwargs)
        self.user_id = user_id

    class Started(AggregateRoot.Created):
        @property
        def user_id(self):
            return self.__dict__['user_id']


@mutator
def todo_list_mutator(initial, event, ):
    return mutate_entity(initial, event)


collection_ns = uuid4()


def make_collection_id(user_id):
    return uuid5(collection_ns, user_id.bytes)


class ProjectionPolicy(object):
    """
    Updates a user's todo list collection.
    """

    def __init__(self, event_store, collection_repo):
        assert isinstance(event_store, AbstractEventStore), type(event_store)
        self.event_store = event_store
        subscribe(self.add_list_to_collection, self.is_list_started)
        # subscribe(self.remove_list_from_collection, self.is_list_discarded)
        self.collection_repo = collection_repo

    def is_list_started(self, event):
        if isinstance(event, (list, tuple)):
            return all(map(self.is_list_started, event))
        return isinstance(event, TodoList.Started)

    def add_list_to_collection(self, event):
        assert isinstance(event, TodoList.Started)
        user_id = event.user_id
        try:
            collection = self.collection_repo[user_id]
        except KeyError:
            collection_id = make_collection_id(user_id)
            collection = register_new_collection(collection_id=collection_id)

        assert isinstance(collection, Collection)
        collection.add_item(event.originator_id)

    def close(self):
        unsubscribe(self.add_list_to_collection, self.is_list_started)


class TodoApp(ApplicationWithPersistencePolicies):
    def __init__(self, session, **kwargs):
        entity_active_record_strategy = SQLAlchemyActiveRecordStrategy(
            active_record_class=IntegerSequencedItemRecord,
            session=session,
        )
        super(TodoApp, self).__init__(
            entity_active_record_strategy=entity_active_record_strategy,
        )
        self.todo_list_collections = CollectionRepository(self.entity_event_store)
        self.projection_policy = ProjectionPolicy(event_store=self.entity_event_store,
                                                  collection_repo=self.todo_list_collections)

    def get_todo_list_collection(self, user_id):
        try:
            collection_id = make_collection_id(user_id)
            collection = self.todo_list_collections[collection_id]
            assert isinstance(collection, Collection)
            return collection.items
        except KeyError:
            return []

    def start_todo_list(self, user_id):
        # Do some work.
        todo_list_id = uuid4()

        # Construct event with results of the work.
        event = TodoList.Started(originator_id=todo_list_id, user_id=user_id)

        # Apply the event to the entity (or aggregate root).
        entity = todo_list_mutator(initial=TodoList, event=event)

        # Publish the event.
        publish(event)

        # Return something.
        return entity


    def close(self):
        super(TodoApp, self).close()
        self.projection_policy.close()