from uuid import uuid4, uuid5, UUID

from eventsourcing.application.base import ApplicationWithPersistencePolicies
from eventsourcing.domain.model.aggregate import AggregateRoot
from eventsourcing.domain.model.collection import Collection, register_new_collection
from eventsourcing.domain.model.decorators import mutator
from eventsourcing.domain.model.entity import mutate_entity
from eventsourcing.domain.model.events import publish, subscribe, unsubscribe
from eventsourcing.infrastructure.eventsourcedrepository import EventSourcedRepository
from eventsourcing.infrastructure.eventstore import AbstractEventStore
from eventsourcing.infrastructure.repositories.collection_repo import CollectionRepository
from eventsourcing.infrastructure.sqlalchemy.activerecords import IntegerSequencedItemRecord, \
    SQLAlchemyActiveRecordStrategy


class TodoApp(ApplicationWithPersistencePolicies):
    def __init__(self, session, **kwargs):
        entity_active_record_strategy = SQLAlchemyActiveRecordStrategy(
            active_record_class=IntegerSequencedItemRecord,
            session=session,
        )
        super(TodoApp, self).__init__(
            entity_active_record_strategy=entity_active_record_strategy,
            **kwargs
        )
        self.todo_lists = EventSourcedRepository(
            mutator=todo_list_mutator,
            event_store=self.entity_event_store
        )
        self.todo_list_collections = CollectionRepository(
            event_store=self.entity_event_store
        )
        self.projection_policy = ProjectionPolicy(
            event_store=self.entity_event_store,
            collection_repo=self.todo_list_collections
        )

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
        return entity.id

    def close(self):
        super(TodoApp, self).close()
        self.projection_policy.close()

    def add_todo_item(self, todo_list_id, item):
        todo_list = self.todo_lists[todo_list_id]
        assert isinstance(todo_list, TodoList)
        todo_list.add_item(item=item)
        todo_list.save()

    def get_todo_items(self, todo_list_id):
        todo_list = self.todo_lists[todo_list_id]
        return tuple(todo_list.items)

    def update_todo_item(self, todo_list_id, index, item):
        todo_list = self.todo_lists[todo_list_id]
        todo_list.update_item(index, item)
        todo_list.save()

    def discard_todo_item(self, todo_list_id, index):
        todo_list = self.todo_lists[todo_list_id]
        todo_list.discard_item(index)
        todo_list.save()

    def discard_todo_list(self, todo_list_id):
        todo_list = self.todo_lists[todo_list_id]
        todo_list.discard()
        todo_list.save()


class TodoList(AggregateRoot):

    def __init__(self, user_id, **kwargs):
        super(TodoList, self).__init__(**kwargs)
        self.user_id = user_id
        self.items = []

    class Event(AggregateRoot.Event):
        """Layer base class."""

    class Started(Event, AggregateRoot.Created):
        """Published when a new list is started."""
        @property
        def user_id(self):
            return self.__dict__['user_id']

    class ItemAdded(Event):
        """Published when an item is added to a list."""
        @property
        def item(self):
            return self.__dict__['item']

        @property
        def list_id(self):
            return self.__dict__['list_id']

    class ItemUpdated(Event):
        """Published when an item is updated in a list."""
        @property
        def index(self):
            return self.__dict__['index']

        @property
        def item(self):
            return self.__dict__['item']

        @property
        def list_id(self):
            return self.__dict__['list_id']

    class ItemDiscarded(Event):
        """Published when an item in a list is discarded."""
        @property
        def index(self):
            return self.__dict__['index']

        @property
        def list_id(self):
            return self.__dict__['list_id']

    class Discarded(Event, AggregateRoot.Discarded):
        @property
        def user_id(self):
            return self.__dict__['user_id']

    def add_item(self, item):
        event = TodoList.ItemAdded(
            originator_id=self.id,
            originator_version=self.version,
            item=item,
        )
        self._apply_and_publish(event)

    def update_item(self, index, item):
        event = TodoList.ItemUpdated(
            originator_id=self.id,
            originator_version=self.version,
            index=index,
            item=item,
        )
        self._apply_and_publish(event)

    def discard_item(self, index):
        event = TodoList.ItemDiscarded(
            originator_id=self.id,
            originator_version=self.version,
            index=index,
        )
        self._apply_and_publish(event)

    def discard(self):
        event = TodoList.Discarded(
            originator_id=self.id,
            originator_version=self.version,
            user_id=self.user_id,
        )
        self._apply_and_publish(event)

    @classmethod
    def _mutate(cls, initial, event):
        return todo_list_mutator(initial or cls, event)


@mutator
def todo_list_mutator(initial, event):
    return mutate_entity(initial, event)


@todo_list_mutator.register(TodoList.Started)
def _(_, event):
    return mutate_entity(initial=TodoList, event=event)


@todo_list_mutator.register(TodoList.ItemAdded)
def _(initial, event):
    assert isinstance(event, TodoList.ItemAdded)
    assert isinstance(initial, TodoList)
    initial.items.append(event.item)
    initial._increment_version()
    return initial

@todo_list_mutator.register(TodoList.ItemUpdated)
def _(initial, event):
    assert isinstance(event, TodoList.ItemUpdated)
    assert isinstance(initial, TodoList)
    initial.items[event.index] = event.item
    initial._increment_version()
    return initial


@todo_list_mutator.register(TodoList.ItemDiscarded)
def _(initial, event):
    assert isinstance(event, TodoList.ItemDiscarded)
    assert isinstance(initial, TodoList)
    initial.items.pop(event.index)
    initial._increment_version()
    return initial


def make_collection_id(user_id, collection_ns=UUID('af3e9b7b-22e0-4758-9b0b-c90949d4838e')):
    return uuid5(collection_ns, user_id.bytes)


class ProjectionPolicy(object):
    """
    Updates a user's todo list collection.
    """

    def __init__(self, event_store, collection_repo):
        assert isinstance(event_store, AbstractEventStore), type(event_store)
        self.event_store = event_store
        subscribe(self.add_list_to_collection, self.is_list_started)
        subscribe(self.remove_list_from_collection, self.is_list_discarded)
        self.collection_repo = collection_repo

    def is_list_started(self, event):
        if isinstance(event, (list, tuple)):
            return all(map(self.is_list_started, event))
        return isinstance(event, TodoList.Started)

    def is_list_discarded(self, event):
        if isinstance(event, (list, tuple)):
            return all(map(self.is_list_discarded, event))
        return isinstance(event, TodoList.Discarded)

    def add_list_to_collection(self, event):
        assert isinstance(event, TodoList.Started)
        user_id = event.user_id
        collection_id = make_collection_id(user_id)
        try:
            collection = self.collection_repo[collection_id]
        except KeyError:
            collection = register_new_collection(collection_id=collection_id)

        assert isinstance(collection, Collection)
        collection.add_item(event.originator_id)

    def remove_list_from_collection(self, event):
        if isinstance(event, (list, tuple)):
            return map(self.remove_list_from_collection, event)

        assert isinstance(event, TodoList.Discarded), event
        user_id = event.user_id
        collection_id = make_collection_id(user_id)
        try:
            collection = self.collection_repo[collection_id]
        except KeyError:
            pass
        else:
            collection.remove_item(event.originator_id)

    def close(self):
        unsubscribe(self.add_list_to_collection, self.is_list_started)
        unsubscribe(self.remove_list_from_collection, self.is_list_discarded)
