from uuid import UUID, uuid5, uuid4

from eventsourcing.application.simple import SimpleApplication
from eventsourcing.domain.model.aggregate import AggregateRoot
from eventsourcing.domain.model.collection import Collection, register_new_collection
from eventsourcing.domain.model.events import subscribe, unsubscribe


USER_LIST_COLLECTION_NS = UUID('af3e9b7b-22e0-4758-9b0b-c90949d4838e')


class TodoList(AggregateRoot):
    """Root entity of todo list aggregate."""

    def __init__(self, user_id, **kwargs):
        super(TodoList, self).__init__(**kwargs)
        self.user_id = user_id
        self.items = []

    @classmethod
    def start(cls, user_id):
        todo_list_id = uuid4()
        return cls.__create__(originator_id=todo_list_id, user_id=user_id, event_class=cls.Started)

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

        def mutate(self, entity):
            entity.items.append(self.item)

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

    class Discarded(Event, AggregateRoot.Discarded):
        """Published when a list is discarded."""

        @property
        def user_id(self):
            return self.__dict__['user_id']

    #
    # Commands.
    #

    def add_item(self, item):
        """Adds item."""
        self.__trigger_event__(
            TodoList.ItemAdded,
            item=item,
        )

    def update_item(self, index, item):
        """Updates item."""
        self.__trigger_event__(
            TodoList.ItemUpdated,
            index=index,
            item=item,
        )

    def discard_item(self, index):
        """Discards item."""
        self.__trigger_event__(
            TodoList.ItemDiscarded,
            index=index,
        )

    def __discard__(self):
        """Discards self."""
        self.__trigger_event__(
            self.Discarded,
            user_id=self.user_id
        )


#
# Event-sourced aggregates.
#

class TodoApp(SimpleApplication):

    persist_event_type = (TodoList.Event, Collection.Event)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_list_projection_policy = UserListProjectionPolicy(self.repository)

    def get_todo_list_ids(self, user_id):
        """Returns list of IDs of to-do lists for a user."""
        collection_id = make_user_list_collection_id(user_id)
        try:
            collection = self.repository[collection_id]
        except KeyError:
            return []
        else:
            assert isinstance(collection, Collection)
            return collection.items

    @staticmethod
    def start_todo_list(user_id):
        """Starts new to-do list for a user."""
        todo_list = TodoList.start(user_id=user_id)
        todo_list.__save__()
        return todo_list.id

    def add_todo_item(self, todo_list_id, item):
        """Added to-do item to a to-do list."""
        todo_list = self.repository[todo_list_id]
        assert isinstance(todo_list, TodoList)
        todo_list.add_item(item=item)
        todo_list.__save__()

    def get_todo_items(self, todo_list_id):
        """Returns a tuple of to-do items."""
        todo_list = self.repository[todo_list_id]
        return tuple(todo_list.items)

    def update_todo_item(self, todo_list_id, index, item):
        """Updates a to-do item in a list."""
        todo_list = self.repository[todo_list_id]
        todo_list.update_item(index, item)
        todo_list.__save__()

    def discard_todo_item(self, todo_list_id, index):
        """Discards a to-do item in a list."""
        todo_list = self.repository[todo_list_id]
        todo_list.discard_item(index)
        todo_list.__save__()

    def discard_todo_list(self, todo_list_id):
        """Discards a to-do list."""
        todo_list = self.repository[todo_list_id]
        todo_list.__discard__()
        todo_list.__save__()

    def close(self):
        super(TodoApp, self).close()
        self.user_list_projection_policy.close()


#
# Projections.
#

class UserListProjectionPolicy(object):
    """
    Updates a user list collection whenever a list is created or discarded.
    """
    def __init__(self, repository):
        self.repository = repository
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
        assert isinstance(event, list)
        event = event[0]
        assert isinstance(event, TodoList.Started)
        user_id = event.user_id
        collection_id = make_user_list_collection_id(user_id)
        try:
            collection = self.repository[collection_id]
        except KeyError:
            collection = register_new_collection(collection_id=collection_id)

        assert isinstance(collection, Collection)
        collection.add_item(event.originator_id)

    def remove_list_from_collection(self, event):
        if isinstance(event, (list, tuple)):
            for e in event:
                self.remove_list_from_collection(e)
            return

        assert isinstance(event, TodoList.Discarded), event
        user_id = event.user_id
        collection_id = make_user_list_collection_id(user_id)
        try:
            collection = self.repository[collection_id]
        except KeyError:
            pass
        else:
            collection.remove_item(event.originator_id)


def make_user_list_collection_id(user_id, collection_ns=USER_LIST_COLLECTION_NS):
    return uuid5(collection_ns, str(user_id))
