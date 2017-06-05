#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from . import logging
from .dllist import dllist, Node

# Many objects in Gruvi need to keep a list of callbacks. This module provides
# a few utility functions to do this in an efficient way.
#
# * Callbacks are stored in a linked list. This allows to iterate over them in
#   insertion order and also allows removal from the middle assuming the node
#   handle is kept by the caller.
# * The add/remove callback functions are implemented as "friend" functions
#   operating on an object. They store the callbacks in the '_callbacks'
#   property of the object.
# * As a special case, a single callback is stored directly in the object as a
#   list node without the overhead of a dllist.


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
    return node.data, node.extra


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
            if not func(node.data, node.extra):
                obj._callbacks = None
        except Exception:
            if log is None:
                log = logging.get_logger()
            log.exception('uncaught exception in callback')
    elif isinstance(callbacks, dllist):
        for node in callbacks:
            try:
                if func(node.data, node.extra):
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
