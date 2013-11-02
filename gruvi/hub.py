#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import signal
import fibers
import collections
import threading
import inspect
import textwrap
import itertools

from . import compat

__all__ = ['switchpoint', 'assert_no_switchpoints', 'get_hub', 'Hub']


# The @switchpoint decorator dynamically compiles the wrapping code at import
# time. The more standard way of returning a closure would result in Sphinx
# documenting the function as having the signature of func(*args, **kwargs).

_switchpoint_template = textwrap.dedent("""\
    def {name}{signature}:
        '''{docstring}'''
        hub = get_hub()
        if getcurrent() is hub:
            raise RuntimeError('cannot call switchpoint from the Hub')
        if hub._atomic:
            raise RuntimeError('switchpoint called from atomic section')
        return _{name}{arglist}
""")

def switchpoint(func):
    """Mark *func* as a switchpoint.

    Use this function as a decorator to mark any method or function that may
    call :meth:`Hub.switch`::

        @switchpoint
        def myfunc():
            # May call Hub.switch here
            pass
    
    You only need to mark methods and functions that invoke :meth:`Hub.switch`
    directly, not via intermediate callables.
    """
    name = func.__name__
    doc = func.__doc__ or ''
    if not doc.endswith('*This method is a switchpoint.*\n'):
        indent = [len(list(itertools.takewhile(str.isspace, line)))
                  for line in doc.splitlines() if line and not line.isspace()]
        indent = indent[0] if len(indent) == 1 else min(indent[1:] or [0])
        doc += '\n\n' + ' ' * indent + '*This method is a switchpoint.*\n'
    argspec = inspect.getargspec(func)
    signature = inspect.formatargspec(*argspec)
    arglist = inspect.formatargspec(*argspec, formatvalue=lambda x: '')
    funcdef = _switchpoint_template.format(name=name, signature=signature,
                                           docstring=doc, arglist=arglist)
    namespace = {'get_hub': get_hub, 'getcurrent': fibers.current,
                 '_{0}'.format(name): func}
    compat.exec_(funcdef, namespace)
    return namespace[name]


class assert_no_switchpoints(object):
    """Context manager to define a block in which no switch points may occur.

    Use this method in case you need to modify a shared state in a non-atomic
    way, and when you're not sure that you're not calling out indirectly to a
    switchpoint::

        with assert_no_switchpoints():
            do_something()
            do_something_else()
    
    If a switchpoint is called while the block is active, an ``AssertionError``
    is raised (even if the switchpoint did not switch).

    This context manager should not be overused. Normally you should know which
    functions are switchpoints or may end up calling switchpoints. Or
    alternatively you could refactor your code to make sure that a global state
    modification is done in a single function and without calling to other
    functions with potentially unknown switching behavior.
    """

    def __enter__(self):
        self._hub = get_hub()
        self._hub._atomic.append(self)

    def __exit__(self, *exc_info):
        assert len(self._hub._atomic) > 0
        ctx = self._hub._atomic.pop()
        assert ctx is self


def get_hub():
    """Return the singleton instance of the hub."""
    return Hub.get()


class Events(object):
    """Synchronize and exchange data via events."""

    def __init__(self):
        self._hub = get_hub()
        self._events = {}

    def wait(self, *events, **kwargs):
        """Suspend the current fiber and wait until a notification is sent
        for any of the events in *events*.
        """
        if not events:
            raise ValueError('specify at least one event')
        for event in events:
            if event in self._events:
                raise RuntimeError('already waiting for event {0}'
                                        .format(event))
        timeout = kwargs.get('timeout')
        switch_back = self._hub.switch_back()
        def on_notify(*args):
            for event in events:
                del self._events[event]
            switch_back(*args)
        for event in events:
            self._events[event] = on_notify
        args = self._hub.switch(timeout)
        assert isinstance(args, tuple)
        if len(args) == 1:
            args = args[0]
        return args

    def notify(self, event, *args):
        """Notify the fiber that is blocked on *event*, if any."""
        callback = self._events.get(event)
        if not callback:
            return False
        callback(*args)
        return True


class Queue(object):
    """A synchronized queue."""

    def __init__(self, on_size_change=None, sizefunc=None):
        """Create a new queue.

        The *on_size_change* argument is an optional callback that will be
        called when the total amount of bytes in the queue changes. This is
        useful for implementing flow control.
        """
        self._queue = collections.deque()
        self._events = Events()
        self._buffer_size = 0
        self._on_size_change = on_size_change
        self._sizefunc = sizefunc or (lambda x: len(x))

    def __len__(self):
        return len(self._queue)

    def _adjust_size(self, delta):
        """Adjust the _buffer_size property."""
        oldsize = self._buffer_size
        self._buffer_size += delta
        if self._on_size_change:
            self._on_size_change(oldsize, self._buffer_size)

    def add(self, obj):
        """Add an object *obj* to the queue."""
        self._queue.append(obj)
        self._adjust_size(self._sizefunc(obj))
        self._events.notify('RequestAdded')

    @switchpoint
    def pop(self):
        """Pop an object from the queue. Wait if the queue is empty."""
        if not self._queue:
            self._events.wait('RequestAdded')
        obj = self._queue.popleft()
        self._adjust_size(-self._sizefunc(obj))
        return obj


class Hub(fibers.Fiber):
    """The central fiber scheduler.

    The root fiber will usually instantiate the Hub by calling the
    :meth:`get` class method, and then start the main event loop by calling
    :meth:`switch`. Typically this loop will remain active during the entire
    life time of the application.

    Non-root fibers use the Hub to wait for certain conditions to become
    true. The condition is normally signalled  by firing a callback. To wait
    until such a callback is fired, a non-root fiber will take the following
    steps:

    1. It will retrieve a new "switchback callback" using :meth:`switch_back`.
    2. It will register the switchback callback as the callback to the condition
       the fiber is interested in.
    3. It will call :meth:`switch` to switch to the Hub to allow other
       fibers to run.
    4. When the condition happens, the switchback callback is called, which
       will schedule a switch back of the current fiber. The execution will
       resume just after the :meth:`switch` call.
    """

    # By default there is one hub per thread
    _local = threading.local()

    def __init__(self, _loop=None):
        if self.current().parent is not None:
            raise RuntimeError('Hub must be created in the root fiber')
        super(Hub, self).__init__(target=self.run)
        self._loop = _loop or pyuv.Loop.default_loop()
        self._atomic = collections.deque()
        self._callbacks = collections.deque()
        from gruvi import logging, util
        self._logger = logging.get_logger(util.objref(self))

    @property
    def loop(self):
        """The pyuv event loop used by this hub instance."""
        return self._loop

    @classmethod
    def get(cls):
        """Return the instance of the hub.

        If no instance exists yet, it will be created. By default, there will
        be one hub instance per Python thread.
        """
        try:
            hub = cls._local.hub
        except AttributeError:
            hub = cls._local.hub = cls()
        return hub

    def run(self):
        # Target of Hub.switch(). This runs the the event loop until there are
        # no more active events, and then switches back to the parent.
        if self.current() is not self:
            raise RuntimeError('run() may only be called from the Hub')
        while True:
            self._run_callbacks()
            with assert_no_switchpoints():
                active = self.loop.run(pyuv.UV_RUN_ONCE)
            if not active and not self._callbacks:
                self.parent.switch()

    def switch(self, timeout=None, interrupt=False):
        """Switch to the hub.

        This method may be called from the root fiber to start or switch to
        the Hub, or from a non-root fiber yield and wait for a switch back.
        The optional *timeout* argument specifies the maximum time to wait. If
        the timeout expires then a switch back is automatically performed.

        If called from the root fiber, then this method returns when there
        are no more callbacks (see :meth:`run_callback`) and no more events in
        the event loop.
        """
        if self.current() is self:
            raise RuntimeError('Cannot switch() to the Hub from the Hub')
        if timeout is not None:
            timer = pyuv.Timer(self.loop)
            timer.start(self.switch_back(), timeout, 0)
        if interrupt:
            sigh = pyuv.Signal(self.loop)
            sigh.start(self.switch_back(), signal.SIGINT)
        ret = super(Hub, self).switch()
        if timeout is not None:
            timer.close()
        if interrupt:
            sigh.close()
        return ret

    def switch_back(self):
        """Return a callback that, when called, queues another callback that
        will switch to the fiber that called ``switch_back()``.

        The callback is often used as the callback target to pyuv methods. At
        the moment, the callback accepts positional arguments only, which are
        returned in a tuple as the result of :meth:`Hub.switch`.
        """
        current = self.current()
        def schedule_switch_back(*args):
            def do_switch_back():
                current.switch(args)
            self.run_callback(do_switch_back)
        return schedule_switch_back

    def _run_callbacks(self):
        """Run registered callbacks."""
        for i in range(len(self._callbacks)):
            callback, args = self._callbacks.popleft()
            try:
                callback(*args)
            except Exception:
                self._logger.exception('Uncaught exception in callback.')

    def run_callback(self, callback, *args):
        """Queue a callback to be called when the event loop next runs.

        The *callback* will be called with *args* in the next iteration of the
        event loop. If you add multiple callbacks, they will be called in the
        order that you added them.
        """
        self._callbacks.append((callback, args))
        self.loop.stop()
