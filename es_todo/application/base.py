from uuid import UUID, uuid4, uuid5

from eventsourcing.application.base import ApplicationWithPersistencePolicies
from eventsourcing.domain.model.aggregate import AggregateRoot
from eventsourcing.domain.model.collection import Collection, register_new_collection
from eventsourcing.domain.model.entity import WithReflexiveMutator
from eventsourcing.domain.model.events import publish, subscribe, unsubscribe
from eventsourcing.infrastructure.eventsourcedrepository import EventSourcedRepository
from eventsourcing.infrastructure.repositories.collection_repo import CollectionRepository
from eventsourcing.infrastructure.sqlalchemy.activerecords import IntegerSequencedItemRecord, \
    SQLAlchemyActiveRecordStrategy

USER_LIST_COLLECTION_NS = UUID('af3e9b7b-22e0-4758-9b0b-c90949d4838e')

#
# Application object.
#

class TodoApp(ApplicationWithPersistencePolicies):
    def __init__(self, session, **kwargs):
        # Construct infrastructure objects for storing events with SQLAlchemy.
        entity_active_record_strategy = SQLAlchemyActiveRecordStrategy(
            active_record_class=IntegerSequencedItemRecord,
            session=session,
        )
        super(TodoApp, self).__init__(
            entity_active_record_strategy=entity_active_record_strategy,
            **kwargs
        )

        # Construct repositories for this application.
        self.todo_lists = EventSourcedRepository(
            mutator=TodoList._mutate,
            event_store=self.entity_event_store
        )
        self.user_list_collections = CollectionRepository(
            event_store=self.entity_event_store
        )

        # Construct policies for this application.
        self.user_list_projection_policy = UserListProjectionPolicy(
            user_list_collections=self.user_list_collections
        )

    #
    # Application services.
    #

    def get_todo_list_ids(self, user_id):
        """Returns list of IDs of todo lists for a user."""
        collection_id = make_user_list_collection_id(user_id)
        try:
            collection = self.user_list_collections[collection_id]
        except KeyError:
            return []
        else:
            assert isinstance(collection, Collection)
            return collection.items

    @staticmethod
    def start_todo_list(user_id):
        """Starts new todo list for a user."""
        event = TodoList.Started(originator_id=uuid4(), user_id=user_id)
        entity = event.mutate(cls=TodoList)
        publish(event)
        return entity.id

    def add_todo_item(self, todo_list_id, item):
        """Added todo item to a todo list."""
        todo_list = self.todo_lists[todo_list_id]
        assert isinstance(todo_list, TodoList)
        todo_list.add_item(item=item)
        todo_list.save()

    def get_todo_items(self, todo_list_id):
        """Returns a tuple of todo items."""
        todo_list = self.todo_lists[todo_list_id]
        return tuple(todo_list.items)

    def update_todo_item(self, todo_list_id, index, item):
        """Updates a todo item in a list."""
        todo_list = self.todo_lists[todo_list_id]
        todo_list.update_item(index, item)
        todo_list.save()

    def discard_todo_item(self, todo_list_id, index):
        """Discards a todo item in a list."""
        todo_list = self.todo_lists[todo_list_id]
        todo_list.discard_item(index)
        todo_list.save()

    def discard_todo_list(self, todo_list_id):
        """Discards a todo list."""
        todo_list = self.todo_lists[todo_list_id]
        todo_list.discard()
        todo_list.save()

    def close(self):
        super(TodoApp, self).close()
        self.user_list_projection_policy.close()


#
# Event-sourced aggregates.
#

class TodoList(WithReflexiveMutator, AggregateRoot):
    """Aggregate root for todo list aggregate."""
    def __init__(self, user_id, **kwargs):
        super(TodoList, self).__init__(**kwargs)
        self.user_id = user_id
        self.items = []

    #
    # Domain events.
    #

    class Event(AggregateRoot.Event):
        """Layer base class."""

    class Started(Event, AggregateRoot.Created):
        """Published when a new list is started."""

        @property
        def user_id(self):
            return self.__dict__['user_id']

        def mutate(self, cls):
            entity = cls(**self.__dict__)
            entity.increment_version()
            return entity

    class ItemAdded(Event):
        """Published when an item is added to a list."""

        @property
        def item(self):
            return self.__dict__['item']

        @property
        def list_id(self):
            return self.__dict__['list_id']

        def mutate(self, entity):
            entity.items.append(self.item)
            entity.increment_version()
            return entity

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

        def mutate(self, entity):
            entity.items[self.index] = self.item
            entity.increment_version()
            return entity

    class ItemDiscarded(Event):
        """Published when an item in a list is discarded."""

        @property
        def index(self):
            return self.__dict__['index']

        @property
        def list_id(self):
            return self.__dict__['list_id']

        def mutate(self, entity):
            entity.items.pop(self.index)
            entity.increment_version()
            return entity

    class Discarded(Event, AggregateRoot.Discarded):
        """Published when a list is discarded."""

        @property
        def user_id(self):
            return self.__dict__['user_id']

        def mutate(self, entity):
            entity._is_discarded = True
            return None

    #
    # Commands.
    #

    def add_item(self, item):
        """Adds item."""
        self._apply_and_publish(
            self._construct_event(
                TodoList.ItemAdded,
                item=item,
            )
        )

    def update_item(self, index, item):
        """Updates item."""
        self._apply_and_publish(
            self._construct_event(
                TodoList.ItemUpdated,
                index=index,
                item=item,
            )
        )

    def discard_item(self, index):
        """Discards item."""
        self._apply_and_publish(
            self._construct_event(
                TodoList.ItemDiscarded,
                index=index,
            )
        )

    def discard(self):
        """Discards self."""
        self._apply_and_publish(
            self._construct_event(
                TodoList.Discarded,
                user_id=self.user_id
            )
        )

    def increment_version(self):
        self._increment_version()

    def _construct_event(self, event_class, **kwargs):
        return event_class(
            originator_id=self.id,
            originator_version=self.version,
            **kwargs
        )

#
# Projections.
#

class UserListProjectionPolicy(object):
    """
    Updates a user list collection whenever a list is created or discarded.
    """

    def __init__(self, user_list_collections):
        self.user_list_collections = user_list_collections
        subscribe(self.add_list_to_collection, self.is_list_started)
        subscribe(self.remove_list_from_collection, self.is_list_discarded)

    def close(self):
        unsubscribe(self.add_list_to_collection, self.is_list_started)
        unsubscribe(self.remove_list_from_collection, self.is_list_discarded)

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
        collection_id = make_user_list_collection_id(user_id)
        try:
            collection = self.user_list_collections[collection_id]
        except KeyError:
            collection = register_new_collection(collection_id=collection_id)

        assert isinstance(collection, Collection)
        collection.add_item(event.originator_id)

    def remove_list_from_collection(self, event):
        if isinstance(event, (list, tuple)):
            return map(self.remove_list_from_collection, event)

        assert isinstance(event, TodoList.Discarded), event
        user_id = event.user_id
        collection_id = make_user_list_collection_id(user_id)
        try:
            collection = self.user_list_collections[collection_id]
        except KeyError:
            pass
        else:
            collection.remove_item(event.originator_id)


def make_user_list_collection_id(user_id, collection_ns=USER_LIST_COLLECTION_NS):
    return uuid5(collection_ns, user_id.bytes)
