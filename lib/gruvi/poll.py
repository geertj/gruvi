#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
from .callbacks import add_callback, remove_callback, walk_callbacks
from .callbacks import has_callback, clear_callbacks

__all__ = ['READABLE', 'WRITABLE']


READABLE = pyuv.UV_READABLE
WRITABLE = pyuv.UV_WRITABLE


if __debug__:

    def dump(mp):
        print('== Dumping MultiPoll {!r}'.format(mp))
        # [total, nreaders, nwriters, nreadwrite, disabled]
        stats = [0, 0, 0, 0, 0]
        def walker(callback, args):
            stats[0] += 1
            if args == READABLE:
                stats[1] += 1
            elif args == WRITABLE:
                stats[2] += 1
            elif args == READABLE|WRITABLE:
                stats[3] += 1
            elif not args:
                stats[4] += 1
            return True
        walk_callbacks(mp, walker)
        print('Using Poll: {!r}'.format(mp._poll))
        print('Poll FD: {}'.format(mp._poll.fileno()))
        print('Total callbacks: {}'.format(stats[0]))
        print('Callbacks registered for read: {}'.format(stats[1]))
        print('Callbacks registered for write: {}'.format(stats[2]))
        print('Callbacks registered for read|write: {}'.format(stats[3]))
        print('Callbacks that are inactive: {}'.format(stats[4]))

    def check(mp):
        counts = [0, 0]  # [readable, writable]
        errors = [0]
        def walker(callback, events):
            if events & READABLE:
                counts[0] += 1
            if events & WRITABLE:
                counts[1] += 1
            if events & ~(READABLE|WRITABLE):
                errors[0] += 1
            return True
        walk_callbacks(mp, walker)
        assert mp._readers == counts[0]
        assert mp._writers == counts[1]
        assert errors[0] == 0
        events = (READABLE if counts[0] > 0 else 0) \
                        | (WRITABLE if counts[1] > 0 else 0)
        assert mp._events == events


class MultiPoll(object):
    """A version of :class:`pyuv.Poll` that allows connecting multiple readers
    and writers to the same file descriptor.
    """

    __slots__ = ('_poll', '_readers', '_writers', '_callbacks', '_events')

    def __init__(self, loop, fd):
        self._poll = pyuv.Poll(loop, fd)
        self._readers = 0
        self._writers = 0
        self._callbacks = None
        self._events = 0

    def _run_callbacks(self, handle, events, error):
        # Run those callbacks that were registered for *events*.
        if error:
            return
        def run_callback(callback, args):
            masked = args & events
            if masked:
                callback(self._poll.fileno(), masked)
            return True  # Keep callback, poll callbacks are persistent
        walk_callbacks(self, run_callback)

    def _sync(self):
        # Synchronize the current set of events with the pyuv.Poll object.
        events = (READABLE if self._readers > 0 else 0) \
                        | (WRITABLE if self._writers > 0 else 0)
        if events == self._events:
            return
        if self._events:
            self._poll.stop()
        if events:
            self._poll.start(events, self._run_callbacks)
        self._events = events

    def add_callback(self, events, callback):
        """Add a new callback."""
        if self._poll is None:
            raise RuntimeError('poll instance is closed')
        if events & ~(READABLE|WRITABLE):
            raise ValueError('illegal event mask: {}'.format(events))
        if events & READABLE:
            self._readers += 1
        if events & WRITABLE:
            self._writers += 1
        handle = add_callback(self, callback, events)
        self._sync()
        return handle

    def remove_callback(self, handle):
        """Remove a callback."""
        if self._poll is None:
            raise RuntimeError('poll instance is closed')
        remove_callback(self, handle)
        if handle.args & READABLE:
            self._readers -= 1
        if handle.args & WRITABLE:
            self._writers -= 1
        self._sync()

    def update_callback(self, handle, events):
        """Update the event mask for a callback."""
        if self._poll is None:
            raise RuntimeError('poll instance is closed')
        if not has_callback(self, handle):
            raise ValueError('no such callback')
        if events & ~(READABLE|WRITABLE):
            raise ValueError('illegal event mask: {}'.format(events))
        if handle.args == events:
            return
        if handle.args & READABLE:
            self._readers -= 1
        if handle.args & WRITABLE:
            self._writers -= 1
        if events & READABLE:
            self._readers += 1
        if events & WRITABLE:
            self._writers += 1
        handle.args = events
        self._sync()

    def close(self):
        """Close the poll instance."""
        if self._poll is None:
            return
        self._poll.close()
        self._poll = None
        self._readers = 0
        self._writers = 0
        self._events = 0
        clear_callbacks(self)


class Poller(object):
    """A flexible file descriptor watcher.

    A Poller can watch multiple file descriptors, and each file descriptors can
    have multiple callbacks registered to it.

    This object is useful when integrating with third party libraries that
    support asynchronous IO by exposing a file descriptor that can be added to
    the event loop.

    Normally you should not instantiate this class yourself. Instead, use the
    per-loop instance that is available as :attr:`Hub.poller`.
    """

    def __init__(self, loop):
        self._loop = loop
        self._mpoll = {}

    def add_callback(self, fd, events, callback):
        """Add a new callback.

        The file descriptor *fd* will be watched for the events specified by
        the *events* parameter, which should be a bitwise OR of the constants
        ``READABLE`` and ``WRITABLE``. Whenever one or more of the specified
        events occur, *callback* will be called with a single integer argument
        containing the bitwise OR of the current events.

        The return value of this method is an opaque handle that can be used
        to remove the callback or to update the events associated with it.
        """
        if self._mpoll is None:
            raise RuntimeError('Poller instance is closed')
        try:
            mpoll = self._mpoll[fd]
        except KeyError:
            mpoll = self._mpoll[fd] = MultiPoll(self._loop, fd)
        handle = mpoll.add_callback(events, callback)
        return handle

    def remove_callback(self, fd, handle):
        """Remove a callback added by :meth:`~Poller.add_callback`.

        If this is the last callback that is registered for the fd then this
        will deallocate the ``MultiPoll`` instance and close the libuv handle.
        """
        if self._mpoll is None:
            raise RuntimeError('Poller instance is closed')
        mpoll = self._mpoll.get(fd)
        if mpoll is None:
            raise ValueError('not watching fd {}'.format(fd))
        mpoll.remove_callback(handle)

    def update_callback(self, fd, handle, events):
        """Update the event mask associated with an existing callback.

        If you want to temporarily disable a callback then you can use this
        method with an *events* argument of ``0``. This is more efficient than
        removing the callback and adding it again later.
        """
        if self._mpoll is None:
            raise RuntimeError('Poller instance is closed')
        mpoll = self._mpoll.get(fd)
        if mpoll is None:
            raise ValueError('not watching fd {}'.format(fd))
        mpoll.update_callback(handle, events)

    def close(self):
        """Close all active poll instances and remove all callbacks."""
        if self._mpoll is None:
            return
        for mpoll in self._mpoll.values():
            mpoll.close()
        self._mpoll.clear()
        self._mpoll = None
