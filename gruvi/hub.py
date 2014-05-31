#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import signal
import collections
import threading
import inspect
import textwrap
import itertools
import six

import pyuv
import fibers

from . import logging, compat
from .errors import Timeout

__all__ = ['switchpoint', 'assert_no_switchpoints', 'switch_back', 'get_hub',
           'Hub', 'sleep']


# The @switchpoint decorator dynamically compiles the wrapping code at import
# time. The more obvious way of using a closure would result in Sphinx
# documenting the function as having the signature of func(*args, **kwargs).

_switchpoint_template = textwrap.dedent("""\
    def {name}{signature}:
        '''{docstring}'''
        hub = get_hub()
        if getcurrent() is hub:
            raise RuntimeError('cannot call switchpoint "{name}" from the Hub')
        if hub._noswitch_depth:
            raise AssertionError('switchpoint called from no-switch section')
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
    # Put the entire docstring on one line so that the line numbers in a
    # @switchpoint traceback match thsoe in _switchpoint_template
    doc = doc.replace('\n', '\\n')
    argspec = inspect.getargspec(func)
    signature = inspect.formatargspec(*argspec)
    arglist = inspect.formatargspec(*argspec, formatvalue=lambda x: '')
    funcdef = _switchpoint_template.format(name=name, signature=signature,
                                           docstring=doc, arglist=arglist)
    code = compile(funcdef, '@switchpoint', 'exec')
    globs = {'get_hub': get_hub, 'getcurrent': fibers.current, '_{0}'.format(name): func}
    six.exec_(code, globs)
    wrapped = globs[name]
    wrapped.func = func
    wrapped.switchpoint = True
    return wrapped


class assert_no_switchpoints(object):
    """Context manager to define a block in which no switchpoints may be called.

    Use this method in case you need to modify a shared state in a non-atomic
    way, and where you want to make suresure that you're not incidentally
    calling out indirectly to a switchpoint::

        with assert_no_switchpoints():
            do_something()
            do_something_else()

    If a switchpoint is called while the block is active, a ``AssertionError``
    is raised (even if the switchpoint did not switch).

    This context manager should not be overused. Normally you should know which
    functions are switchpoints or may end up calling switchpoints. Or
    alternatively you could refactor your code to make sure that a global state
    modification is done in a single leaf function.
    """

    __slots__ = ('_hub',)

    def __init__(self, hub=None):
        self._hub = hub or get_hub()

    def __enter__(self):
        self._hub._noswitch_depth += 1

    def __exit__(self, *exc_info):
        assert self._hub._noswitch_depth > 0
        self._hub._noswitch_depth -= 1
        self._hub = None


class switch_back(object):
    """A switch back object.

    A switch back object is a callable object that can be used to switch back
    to the current fiber after the latter has switched to the hub via
    :meth:`Hub.switch`.

    Idiomatic use of a switchback object is as follows::

      with switch_back(timeout) as switcher:
          start_async_job(job, callback=switcher)
          hub.switch()

    In this code fragment, ``start_async_job`` is a function that starts an
    asynchronous job that will call the passed callback when it is done.  After
    the job started, the fiber switches to the hub using :meth:`Hub.switch`.
    This causes the event loop to run. Once the asynchronous job is done, the
    switchback instance is called, which schedules a switch back, which in turn
    makes :meth:`Hub.switch` return.
    """

    __slots__ = ('_timeout', '_hub', '_fiber', '_cancelled', '_timer')

    def __init__(self, timeout=None, hub=None):
        """
        The a *timeout* argument of can be used to force a timeout after this
        many seconds. If a timeout happens, :meth:`Hub.switch` will raise a
        :class:`Timeout` exception. The default is None, meaning there is no
        timeout.

        The *hub* argument can be used to specfiy an alternate hub to use.
        By default, the Hub returned by :func:`get_hub` is used.
        """
        self._timeout = timeout
        self._hub = hub or get_hub()
        self._fiber = fibers.current()
        self._cancelled = False

    fiber = property(lambda self: self._fiber)
    timeout = property(lambda self: self._timeout)

    def __enter__(self):
        if self._timeout is not None:
            self._timer = pyuv.Timer(self._hub.loop)
            self._timer.start(self, self._timeout, 0)
        return self

    def __exit__(self, *exc_info):
        if self._timeout is not None:
            if not self._timer.closed:
                self._timer.close()
            self._timer = None
        self._cancelled = True
        self._hub = None
        self._fiber = None

    def throw(self, exc):
        """Cause :meth:`Hub.switch` to raise an exception."""
        if self._cancelled or not self.fiber.is_alive():
            return
        self._hub.run_callback(self.fiber.switch, exc)

    def __call__(self, *args, **kwargs):
        if self._cancelled or not self.fiber.is_alive():
            return
        if self._timeout is not None and args == (self._timer,):
            value = Timeout('Timeout in switch_back() block')
        else:
            value = (args, kwargs)
        self._hub.run_callback(self.fiber.switch, value)


_local = threading.local()

def get_hub():
    """Return the singleton instance of the hub.

    By default there is one Hub per thread.
    """
    try:
        hub = _local.hub
    except AttributeError:
        hub = _local.hub = Hub()
    return hub


class Hub(fibers.Fiber):
    """The central fiber scheduler.

    The hub is created automatically the first time it is needed, so it is not
    necessary to instantiate this class yourself.

    By default there is one hub per thread. To access the per thread instance,
    use :func:`get_hub`.

    The hub is used by fibers to pause themselves until a wake-up condition
    becomes true. See the documentation for :class:`switch_back` for details.

    Callbacks can be run in the hub's fiber by using :meth:`run_callback`.
    """

    # By default the Hub honors CTRL-C
    ignore_interrupt = False

    def __init__(self):
        if self.parent is not None:
            raise RuntimeError('Hub must be created in the root fiber')
        super(Hub, self).__init__(target=self.run)
        self.name = 'Hub'
        self.context = ''
        self._loop = pyuv.Loop()
        self._data = {}
        self._noswitch_depth = 0
        self._callbacks = collections.deque()
        # Thread IDs may be recycled when a thread exits. But as long as the
        # hub is alive, it won't be recycled so in that case we can use just
        # the ID as a check whether we are in the same thread or not.
        self._thread = compat.get_thread_ident()
        self._stop_loop = pyuv.Async(self._loop, lambda h: self._loop.stop())
        self._term_loop = pyuv.Signal(self._loop)
        self._term_loop.start(self._on_sigint, signal.SIGINT)
        self._log = logging.get_logger()
        self._log.debug('new Hub for {.name}', threading.current_thread())
        self._closing = False
        self._error = None

    @property
    def loop(self):
        """The pyuv event loop used by this hub instance."""
        return self._loop

    @property
    def data(self):
        """A per-hub dict that can be used by applications to store data."""
        return self._data

    def _on_sigint(self, h, signo):
        # SIGINT handler. Terminate the hub and switch back to the root, where
        # a KeyboardInterrupt will be raised.
        if self.ignore_interrupt:
            return
        self._error = KeyboardInterrupt('CTRL-C pressed')
        self.close()

    def _interrupt_loop(self):
        # Interrupt the event loop
        if compat.get_thread_ident() == self._thread:
            self._loop.stop()
        else:
            self._stop_loop.send()

    def close(self):
        """Close the hub.

        This stops the event loop, and causes the hub fiber to exit and
        switch back to the root fiber.

        This method is thread-safe. It is allowed call this method from a
        different thread than the one running the Hub.
        """
        if self._loop is None:
            return
        self._closing = True
        self._interrupt_loop()

    def run(self):
        # Target of Hub.switch().
        if self.current() is not self:
            raise RuntimeError('run() may only be called from the Hub')
        self._log.debug('starting hub fiber')
        while True:
            self._run_callbacks()
            if self._closing:
                break
            with assert_no_switchpoints(self):
                self._loop.run()
        # Hub is going to exit at this point. Clean everyting up.
        for handle in self._loop.handles:
            if not handle.closed:
                handle.close()
        # Run the loop until all asynchronous closes are handled.
        # For some reason it appears this needs to be run twice.
        while self._loop.run():
            self._log.debug('run loop another time to close handles')
        if getattr(_local, 'hub', None) is self:
            del _local.hub
        self._loop = None
        self._callbacks.clear()
        self._stop_loop = None
        self._term_loop = None
        self._log.debug('hub fiber terminated')
        if self._error:
            raise compat.saved_exc(self._error)

    def switch(self):
        """Switch to the hub.

        This method pauses the current fiber and runs the event loop.

        The caller should ensure that it has set up appropriate switchbacks
        using :class:`switch_back`. If a switchback was called, the return
        value is an ``(args, kwargs)`` tuple containing its arguments.  If a
        timeout or another exception was raised by the switchback, the
        exception is re-raised here.

        If this method is called from the root fiber then there is an
        additional case if the hub exited. If the hub exited due to a call to
        :meth:`close` then this method returns None. And if the hub exited due
        to a exception, that exception is re-raised here.
        """
        if self._loop is None or not self.is_alive():
            raise RuntimeError('hub is closed/dead')
        elif self.current() is self:
            raise RuntimeError('cannot switch to myself')
        elif compat.get_thread_ident() != self._thread:
            raise RuntimeError('cannot switch from a different thread')
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
        if self._loop is None:
            raise RuntimeError('hub is closed')
        elif not callable(callback):
            raise TypeError('"callback": expecting a callable')
        self._callbacks.append((callback, args))  # atomic
        self._interrupt_loop()


@switchpoint
def sleep(secs):
    """Sleep for *secs* seconds."""
    hub = get_hub()
    try:
        with switch_back(secs):
            hub.switch()
    except Timeout:
        pass
