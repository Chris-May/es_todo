# -8- coding: utf-8 -*-
from uuid import uuid4

from eventsourcing.infrastructure.sqlalchemy.datastore import SQLAlchemyDatastore, SQLAlchemySettings

from es_todo.application.base import TodoApp

"""
I might start by identifying some domain events - things that might happen in the domain of "todo lists":

- Todo list started
- Todo item added
- Todo item updated
- Todo item discarded
- Todo list discarded

Then I might start to think about which commands might cause those events to be constructed:

- Start todo list (=> Todo list started)
- Add todo item (=> Todo item added)
- Update todo item (=> Todo item updated)
- Discard todo item (=> Todo item discarded)
- Discard todo list (=> Todo list discarded)

Then I might start to think about which aggregate(s) would most usefully respond to the commands and emit the events.

- Todo List (an aggregate, with operations to add item, update item, discard item, discard list - the operations are 
coded to publish the events implied by the command, as above)

We also need a factory method to start a new list.

- Todo List Factory (start new list, which emits the "Todo list started" event)

Then I might start to think about which views I need to construct those commands:

- My collection of todo lists (needed to check I'm not duplicating a list I already started, and also pick a todo 
list before I can add a list)

To update the view, we need to have a policy:

- Whenever a new todo list is started by a user, add the todo list ID to the collection of todo lists for that user.

Then I would make an application object that has the factory, a repository for the todo list aggregates, the policy, 
and the view which gives the collection of lists for a given user.

Then I might make an interface that presents the application, with a screen to authenticate, a screen to show all 
the todo lists for an authenticated user, which allows a new list to be started, a screen that shows an individual 
todo list with all its items, that allows items to be added, updated and discarded, and which allows the list to be 
discarded perhaps with a warning.

Would it work? What do you think? It's a start, right? That "analysis" took me about 25 minutes. It doesn't need to 
be heavy work.


For the tests, just think about the things you might want to do with the application object. First you perhaps want 
to see the collection of todo lists is empty for a user. Then you could start a todo list, and check the collection 
has one list. Then you could get the list from the repository, and check it has no items. Then you could add an item 
to the list. Then you could get the list again, and check it has one item. Then you could update the item. Then you 
could get the list and see it has the updated item. Then you could discard the item, and check by getting the list 
and checking it has no items. Then you could discard the list, and get the collection, and check the collection has 
no items.

To code this, you can inherit from the library application class (as you have done) and give it the bits and pieces 
I described above: the factory, the repository of lists. The view could be implemented in different ways.

At first, you could just do something really naive with simple Python objects. That would allow you to write the 
policy, and get the tests passing.

Also to keep things simple, you could at first not have any users. And then when the todo lists are working, 
and there is a view and a policy, then add more than one user (which would need more tests than I said above).

Then you could make the view (collection of todo lists for each user) persistent, by having its own table. It would 
also be possible to have an event sourced collection of todo lists for each user, so there would be two repositories 
(one for the todo list aggregates, and another for the collection of todo lists).
"""


def test():
    # Construct application.
    app = TodoApp()

    # Check the user initially has no lists.
    user_id = uuid4()
    todo_list_ids = app.get_todo_list_ids(user_id)
    assert todo_list_ids == []

    # Start a new list.
    todo_list_id = app.start_todo_list(user_id)

    # Check the user has one list.
    todo_list_ids = app.get_todo_list_ids(user_id)
    assert todo_list_ids == {todo_list_id}

    # Check the list has no items.
    assert app.get_todo_items(todo_list_id) == ()

    # Add an item to the list.
    app.add_todo_item(todo_list_id=todo_list_id, item='item1')

    # Check the list has one item.
    assert app.get_todo_items(todo_list_id) == ('item1',)

    # Update the item.
    app.update_todo_item(todo_list_id=todo_list_id, index=0, item='item1.1')

    # Get the list and see it has the updated item.
    assert app.get_todo_items(todo_list_id) == ('item1.1',)

    # Discard the item, and check by getting the list and checking it has no items.
    app.discard_todo_item(todo_list_id=todo_list_id, index=0)
    assert app.get_todo_items(todo_list_id) == ()

    # Discard the list, and check there are no list IDs for the user.
    app.discard_todo_list(todo_list_id=todo_list_id)
    todo_list_ids = app.get_todo_list_ids(user_id)
    assert len(todo_list_ids) == 0
