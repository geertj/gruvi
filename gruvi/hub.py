#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import signal
import collections
import threading
import inspect
import textwrap
import itertools
import weakref

import pyuv
import fibers

from . import compat, logging
from .error import Timeout

__all__ = ['assert_no_switchpoints', 'get_hub', 'switchpoint', 'switch_back', 'Hub']


# The @switchpoint decorator dynamically compiles the wrapping code at import
# time. The more obvious way of using a closure would result in Sphinx
# documenting the function as having the signature of func(*args, **kwargs).

_switchpoint_template = textwrap.dedent("""\
    def {name}{signature}:
        '''{docstring}'''
        hub = get_hub()
        if getcurrent() is hub:
            raise RuntimeError('cannot call switchpoint "{name}" from the Hub')
        if hub._atomic:
            raise RuntimeError('switchpoint called from atomic section')
        return _{name}{arglist}
""")

def switchpoint(func):
    """Mark *func* as a switchpoint.

    Use this function as a decorator to mark any method or function that may
    call :meth:`Hub.switch`, as follows::

        @switchpoint
        def myfunc():
            # May call Hub.switch() here
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
    """Context manager to define a block in which no switchpoints may occur.

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
    modification is done in a single leaf function.
    """

    def __init__(self, hub=None):
        self._hub = hub or get_hub()

    def __enter__(self):
        self._hub._atomic.append(self)

    def __exit__(self, *exc_info):
        assert len(self._hub._atomic) > 0
        ctx = self._hub._atomic.pop()
        assert ctx is self
        self._hub = None


class switch_back(object):
    """A switch back object.

    A switch back object is a callable object that can be used to switch back
    to the current fiber after it has switched to the hub via
    :meth:`Hub.switch`.

    Idiomatic use of a switchback instance is as follows::

      with switch_back(timeout) as switcher:
          start_async_job(job, callback=switcher)
          hub.switch()

    In this code fragment, ``start_async_job`` is a function that starts an
    asynchronous job that calls the passed callback when it is done.  After the
    job started, the fiber switches to the hub using :meth:`Hub.switch`. This
    will cause the event loop to run. Once the asynchronous job is done, the
    switchback instance is called, which schedules a switch back, which in turn
    makes :meth:`Hub.switch` return.
    """

    def __init__(self, timeout=None, interrupt=False, hub=None):
        """
        The a *timeout* argument of can be used to force a timeout after this
        many seconds. If a timeout happens, :meth:`Hub.switch` will raise a
        :class:`Timeout` exception. The default is None, meaning there is no
        timeout.

        The *interrupt* argument is a flag that allows to you interrupt the hub
        via CTRL-C or similar. In this case, :meth:`Hub.switch` will raise a
        :class:`KeyboardInterrupt`. The default is false, meaning CTRL-C will
        not interrupt the hub.

        The *hub* argument can be used to specfiy an alternate hub to use for
        the timeout and interrupt handles, and to schedule the switchback. By
        default, the hub of the current thread is used.
        """
        self._timeout = timeout
        self._interrupt = interrupt
        self._hub = hub or get_hub()
        self._fiber = fibers.current()
        self._cancelled = False

    fiber = property(lambda self: self._fiber)
    timeout = property(lambda self: self._timeout)
    interrupt = property(lambda self: self._interrupt)
    cancelled = property(lambda self: self._cancelled)

    def __enter__(self):
        if self._timeout is not None:
            self._timer = pyuv.Timer(self._hub.loop)
            self._timer.start(self, self._timeout, 0)
        if self._interrupt:
            self._signal = pyuv.Signal(self._hub.loop)
            self._signal.start(self, signal.SIGINT)
        return self

    def __exit__(self, *exc_info):
        if self._timeout is not None:
            self._timer.close()
            self._timer = None
        if self._interrupt:
            self._signal.close()
            self._signal = None
        self._cancelled = True
        self._hub = None
        self._fiber = None

    cancel = __exit__

    def __call__(self, *args, **kwargs):
        if self.cancelled or not self.fiber.is_alive():
            return
        if self._timeout is not None and args == (self._timer,):
            value = Timeout('Timeout in switch_back() block')
        elif self._interrupt and args == (self._signal,):
            value = KeyboardInterrupt('CTRL-C pressed in switch_back() block')
        else:
            value = (args, kwargs)
        self._hub.run_callback(self.fiber.switch, value)


def get_hub():
    """Return the singleton instance of the hub.
    
    By default there is one Hub per thread.
    This method is equivalent to :meth:`Hub.get`.
    """
    return Hub.get()


class Hub(fibers.Fiber):
    """The central fiber scheduler.

    The hub is created automatically the first time it is needed, so it is not
    necessary to instantiate this class yourself.

    There is always one hub per thread. To access the per thread instance, use
    :meth:`Hub.get` or the function :func:`get_hub` which is an alias.

    The hub is used by fibers to wait for certain conditions to become true.
    See the documentation for :class:`switch_back` for details.

    Callbacks can be run in the hub's fiber by using :meth:`run_callback`.

    The hub also manages a thread pool that can be used for performing blocking
    IO or CPU intensive tasks. See :meth:`run_in_threadpool`.
    """

    def __init__(self):
        if self.parent is not None:
            raise RuntimeError('Hub must be created in the root fiber')
        super(Hub, self).__init__(target=self.run)
        self._loop = pyuv.Loop()
        self._atomic = collections.deque()
        self._callbacks = collections.deque()
        self._thread = threading.get_ident()
        self._stop_loop = pyuv.Async(self.loop, lambda h: self.loop.stop())
        self._log = logging.get_logger(self)
        self._log.debug('new Hub for thread {:#x}', self._thread)

    @property
    def loop(self):
        """The pyuv event loop used by this hub instance."""
        return self._loop

    _local = threading.local()

    @classmethod
    def get(cls):
        """Return the thread specific instance of the Hub."""
        try:
            hub = cls._local.hub
        except AttributeError:
            cls._local.hub = Hub()
        return cls._local.hub

    def close(self):
        """Stop the hub."""
        if not self.is_alive():
            raise RuntimeError('hub has already been stopped')
        if self.current() is self or self.current().parent is not None:
            raise RuntimeError('close() must be called from the root fiber')
        # Close all the handles, and then let the loop exit. This gives the
        # loop the opportunity to process all the asynchronous close() calls.
        def closer(h):
            if not h.closed:
                h.close()
        self.loop.walk(closer)
        self.switch()  # will terminate self.run(), and switch back to us
        if hasattr(self._local, 'hub'):
            del self._local.hub
        self._loop = None
        self._callbacks.clear()
        self._log.debug('hub terminated via close()')

    def run(self):
        # Target of Hub.switch().
        if self.current() is not self:
            raise RuntimeError('run() may only be called from the Hub')
        self._log.debug('starting event loop')
        while True:
            self._run_callbacks()
            with assert_no_switchpoints(self):
                active = self.loop.run()
            if not active:
                break
        self._log.debug('event loop terminated')

    def switch(self):
        """Switch to the hub.

        This method pauses the current fiber and runs the event loop. The
        calling fiber should ensure that it has set up appropriate switchbacks
        using :class:`switch_back`.

        Return value is the ``value`` argument passed to :meth:`Fiber.switch`.
        """
        if threading.get_ident() != self._thread:
            raise RuntimeError('cannot switch form a different thread')
        value = super(Hub, self).switch()
        if isinstance(value, Exception):
            raise value
        return value

    def _run_callbacks(self):
        """Run registered callbacks."""
        for i in range(len(self._callbacks)):
            callback, args = self._callbacks.popleft()
            try:
                callback(*args)
            except Exception:
                self._log.exception('Uncaught exception in callback.')

    def run_callback(self, callback, *args):
        """Queue a callback to be called when the event loop next runs.

        The *callback* will be called with positional arguments *args* in the
        next iteration of the event loop. If you add multiple callbacks, they
        will be called in the order that you added them. The callback will run
        in the Hub's fiber.

        This method is thread-safe. It is allowed to queue a callback from a
        different thread than the one running the Hub.
        """
        self._callbacks.append((callback, args))  # atomic
        if threading.get_ident() == self._thread:
            self.loop.stop()
        else:
            self._stop_loop.send()
