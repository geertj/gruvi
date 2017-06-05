#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from . import logging


# Linked list implementation, used by gruvi.callbacks and others.

if __debug__:

    def fmtnode(node):
        return '<Node(prev={:#x}, next={:#x}, data={!r})>' \
                    .format(id(node._prev), id(node._next), node.data)

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

    __slots__ = ('_prev', '_next', '_list', 'data', 'extra')

    def __init__(self, data=None, extra=None):
        self._prev = None
        self._next = None
        self._list = None
        self.data = data
        self.extra = extra


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
