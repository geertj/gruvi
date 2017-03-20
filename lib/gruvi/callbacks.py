#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from . import logging

# Many objects in Gruvi need to keep a list of callbacks. This module provides
# a few utility functions to do this in an efficient way.
#
# Callbacks are stored in a linked list. This allows to iterate over them in
# insertion order and also allows removal from the middle assuming the node
# handle is kept by the caller.

# Linked list implementation:

if __debug__:

    def fmtnode(node):
        return '<Node(prev={:#x}, next={:#x}, value={!r})>' \
                    .format(id(node._prev), id(node._next), node.value)

    def dump(dll):
        print('== Dumping dllist {!r}'.format(dll))
        print('Size: {}'.format(dll._size))
        print('First: {}'.format(fmtnode(dll.first) if dll.first else 'None'))
        print('Last: {}'.format(fmtnode(dll.last) if dll.last else 'None'))
        print('Nodes:')
        count = 0
        node = dll.first
        while node is not None:
            print('- {} [{}]'.format(fmtnode(node), count))
            node = node._next
            count += 1
        print('Total nodes: {}'.format(count))

    def check(dll):
        if dll.first is None:
            assert dll.last is None
            assert dll._size == 0
            return
        node = dll.first
        assert node._list is dll
        assert node._prev is None
        nnode = node._next
        count = 1
        while nnode is not None:
            assert nnode._list is dll
            assert nnode._prev is node
            node, nnode = nnode, nnode._next
            count += 1
        assert node is dll.last
        assert count == dll._size


class Node(object):
    """A node in a doubly linked list."""

    __slots__ = ('_prev', '_next', '_list', 'callback', 'args')

    def __init__(self, callback=None, args=None):
        self._prev = None
        self._next = None
        self._list = None
        self.callback = callback
        self.args = args


class dllist(object):
    """A doubly linked list."""

    __slots__ = ('_first', '_last', '_size')

    def __init__(self):
        self._first = None
        self._last = None
        self._size = 0

    @property
    def first(self):
        """The first node in the list."""
        return self._first

    @property
    def last(self):
        """The last node in the list."""
        return self._last

    def __len__(self):
        return self._size

    def __contains__(self, node):
        """Return whether *node* is contained in the list."""
        if not isinstance(node, Node):
            raise TypeError('expecting Node instance')
        return node._list is self

    def remove(self, node):
        """Remove a node from the list."""
        if not isinstance(node, Node):
            raise TypeError('expecting Node instance')
        if node._list is None:
            return
        if node._list is not self:
            raise RuntimeError('node is not contained in list')
        if node._next is None:
            self._last = node._prev  # last node
        else:
            node._next._prev = node._prev
        if node._prev is None:
            self._first = node._next  # first node
        else:
            node._prev._next = node._next
        node._list = node._prev = node._next = None
        self._size -= 1

    def insert(self, node, before=None):
        """Insert a new node in the list.

        If *before* is specified, the new node is inserted before this node.
        Otherwise, the node is inserted at the end of the list.
        """
        node._list = self
        if self._first is None:
            self._first = self._last = node  # first node in list
            self._size += 1
            return node
        if before is None:
            self._last._next = node  # insert as last node
            node._prev = self._last
            self._last = node
        else:
            node._next = before
            node._prev = before._prev
            if node._prev:
                node._prev._next = node
            else:
                self._first = node  # inserting as first node
            node._next._prev = node
        self._size += 1
        return node

    def __iter__(self):
        """Return an iterator/generator that yields all nodes.

        Note: it is safe to remove the current node while iterating but you
        should not remove the next one.
        """
        node = self._first
        while node is not None:
            next_node = node._next
            yield node
            node = next_node

    def clear(self):
        """Remove all nodes from the list."""
        node = self._first
        while node is not None:
            next_node = node._next
            node._list = node._prev = node._next = None
            node = next_node
        self._size = 0


# Callback utilities. These utilities add some more optimizations.
#
# * The add/remove callback functions are implemented as functions operating on
#   an object. They store the callbacks in the '_callbacks' property of the
#   object.
# * A single callback is stored directly in the object as a Node.
# * Multiple calbacks are stored as a dllist of nodes.


def add_callback(obj, callback, args=()):
    """Add a callback to an object."""
    callbacks = obj._callbacks
    node = Node(callback, args)
    # Store a single callback directly in _callbacks
    if callbacks is None:
        obj._callbacks = node
        return node
    # Otherwise use a dllist.
    if not isinstance(callbacks, dllist):
        obj._callbacks = dllist()
        obj._callbacks.insert(callbacks)
        callbacks = obj._callbacks
    callbacks.insert(node)
    return node


def remove_callback(obj, handle):
    """Remove a callback from an object."""
    callbacks = obj._callbacks
    if callbacks is handle:
        obj._callbacks = None
    elif isinstance(callbacks, dllist):
        callbacks.remove(handle)
        if not callbacks:
            obj._callbacks = None


def has_callback(obj, handle):
    """Return whether a callback is currently registered for an object."""
    callbacks = obj._callbacks
    if not callbacks:
        return False
    if isinstance(callbacks, Node):
        return handle is callbacks
    else:
        return handle in callbacks


def pop_callback(obj):
    """Pop a single callback."""
    callbacks = obj._callbacks
    if not callbacks:
        return
    if isinstance(callbacks, Node):
        node = callbacks
        obj._callbacks = None
    else:
        node = callbacks.first
        callbacks.remove(node)
        if not callbacks:
            obj._callbacks = None
    return node.callback, node.args


def clear_callbacks(obj):
    """Remove all callbacks from an object."""
    callbacks = obj._callbacks
    if isinstance(callbacks, dllist):
        # Help the garbage collector by clearing all links.
        callbacks.clear()
    obj._callbacks = None


def walk_callbacks(obj, func, log=None):
    """Call func(callback, args) for all callbacks and keep only those
    callbacks for which the function returns True."""
    callbacks = obj._callbacks
    if isinstance(callbacks, Node):
        node = callbacks
        try:
            if not func(node.callback, node.args):
                obj._callbacks = None
        except Exception:
            if log is None:
                log = logging.get_logger()
            log.exception('uncaught exception in callback')
    elif isinstance(callbacks, dllist):
        for node in callbacks:
            try:
                if func(node.callback, node.args):
                    continue
                callbacks.remove(node)
            except Exception:
                if log is None:
                    log = logging.get_logger()
                log.exception('uncaught exception in callback')
        if not callbacks:
            obj._callbacks = None


def run_callbacks(obj, log=None):
    """Run callbacks."""
    def run_callback(callback, args):
        return callback(*args)
    return walk_callbacks(obj, run_callback, log)
