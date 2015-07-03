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
import textwrap
import itertools
import traceback

import pyuv
import fibers

from . import logging, compat, util
from .errors import Timeout
from .callbacks import add_callback, run_callbacks
from .poll import Poller

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

def switchpoint(func, update_doc=True):
    """Mark *func* as a switchpoint.

    In Gruvi, all methods and functions that call :meth:`Hub.switch` directly,
    and all public APIs that can cause an indirect switch, are marked as a
    switchpoint. It is recommended that you mark your own methods and functions
    in the same way. Example::

      @switchpoint
      def myfunc():
          # may call Hub.switch() here
    """
    name = func.__name__
    doc = func.__doc__ or ''
    if update_doc and not doc.endswith('*This method is a switchpoint.*\n'):
        indent = [len(list(itertools.takewhile(str.isspace, line)))
                  for line in doc.splitlines() if line and not line.isspace()]
        indent = indent[0] if len(indent) == 1 else min(indent[1:] or [0])
        doc += '\n\n' + ' ' * indent + '*This method is a switchpoint.*\n'
        func.__doc__ = doc
    globs = {'get_hub': get_hub, 'getcurrent': fibers.current, '_{}'.format(name): func}
    wrapped = util.wrap(_switchpoint_template, func, globs, 2)
    wrapped.func = func
    wrapped.switchpoint = True
    return wrapped


class assert_no_switchpoints(object):
    """Context manager that defines a block in which no switches may happen,
    and in which no switchpoints may be called.

    Use it as follows::

      with assert_no_switchpoints():
          do_something()
          do_something_else()

    If the context manager detects a switch or a call into a switchpoint it
    raises an :exc:`AssertionError`.
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
    """A context manager to facilitate switching back to the current fiber.

    Instances of this class are callable, and are intended to be used as the
    callback argument for an asynchronous operation. When called, the
    switchback object causes :meth:`Hub.switch` to return in the *origin* fiber
    (the fiber that created the switchback object). The return value in the
    origin fiber will be an ``(args, kwargs)`` tuple containing positional and
    keyword arguments passed to the callback.

    When the context manager exits it will be deactivated. If it is called
    after that then no switch will happen. Also the cleanup callbacks are run
    when the context manager exits.

    In the example below, a switchback object is used to wait for at most 10
    seconds for a SIGHUP signal::

      hub = get_hub()
      with switch_back(timeout=10) as switcher:
          sigh = pyuv.Signal(hub.loop)
          sigh.start(switcher, signal.SIGHUP)
          switcher.add_cleanup(sigh.close)
          hub.switch()
    """

    __slots__ = ('_timeout', '_hub', '_fiber', '_timer', '_callbacks', '_lock')

    def __init__(self, timeout=None, hub=None, lock=None):
        """
        The *timeout* argument can be used to force a timeout after this many
        seconds. It can be an int or a float. If a timeout happens,
        :meth:`Hub.switch` will raise a :class:`Timeout` exception in the
        origin fiber. The default is None, meaning there is no timeout.

        The *hub* argument can be used to specify an alternate hub to use.
        This argument is used by the unit tests and should normally not be
        needed.
        """
        self._timeout = timeout
        self._hub = hub or get_hub()
        self._fiber = fibers.current()
        self._callbacks = None
        self._lock = lock

    @property
    def fiber(self):
        """The origin fiber."""
        return self._fiber

    @property
    def timeout(self):
        """The :class:`~gruvi.Timeout` exception if a timeout has occurred.
        Otherwise the *timeout* parameter provided to the constructor."""
        return self._timeout

    @property
    def active(self):
        """Whether the switchback object is currently active."""
        return bool(self._hub and self._fiber.is_alive())

    def switch(self, value=None):
        """Switch back to the origin fiber. The fiber is switch in next time
        the event loop runs."""
        if self._hub is None or not self._fiber.is_alive():
            return
        self._hub.run_callback(self._fiber.switch, value)
        self._hub = self._fiber = None  # switch back at most once!

    def throw(self, *exc_info):
        """Throw an exception into the origin fiber. The exception is thrown
        the next time the event loop runs."""
        # The might seem redundant with self._fiber.cancel(exc), but it isn't
        # as self._fiber might be a "raw" fibers.Fiber() that doesn't have a
        # cancel() method.
        if self._hub is None or not self._fiber.is_alive():
            return
        self._hub.run_callback(self._fiber.throw, *exc_info)
        self._hub = self._fiber = None  # switch back at most once!

    def add_cleanup(self, callback, *args):
        """Add a cleanup action. The callback is run with the provided
        positional arguments when the context manager exists."""
        add_callback(self, callback, args)

    def __enter__(self):
        if self._timeout is not None:
            # There are valid scenarios for a Gruvi application where the loop
            # will not run for a long time. For example, a single fiber program
            # that only calls out to the loop to perform a blocking action.
            # Since a timer captures loop->time at when it is created, we need
            # to make sure the loop's time is up to date. That's why we call
            # update_time().
            self._hub.loop.update_time()
            self._timer = pyuv.Timer(self._hub.loop)
            self._timer.start(self, self._timeout, 0)
        return self

    def __exit__(self, *exc_info):
        if self._timeout is not None:
            self._timer.close()
            self._timer = None
        run_callbacks(self)

    def __call__(self, *args, **kwargs):
        # This method is thread safe if a lock was passed into the constructor
        # (and is the only method in this class for which this is the case).
        # This functionality is provided because this class is used by thread
        # safe objects where it can happen that the timeout and the regular
        # invocation of this method can happen in different threads.
        if self._lock:
            self._lock.acquire()
        try:
            if self._timeout is not None and args == (self._timer,):
                self._timeout = Timeout('timeout in switch_back() block')
                self.throw(Timeout, self._timeout)
            else:
                self.switch((args, kwargs))
        finally:
            if self._lock:
                self._lock.release()


_local = threading.local()

def get_hub():
    """Return the instance of the hub."""
    try:
        hub = _local.hub
    except AttributeError:
        hub = _local.hub = Hub()
    return hub


class Hub(fibers.Fiber):
    """The central fiber scheduler and event loop manager."""

    # The hub is created automatically the first time it is needed,so it is not
    # necessary to instantiate this class yourself.
    #
    # By default there is one hub per thread. To access the per thread instance,
    # use get_hub()
    #
    # The hub is used by fibers to pause themselves until a wake-up condition
    # becomes true. See the documentation for switch_back for details

    #: When CTRL-C is pressed, the default action taken by the Hub is to call
    #: its own :meth:`close` method. Set this attribute to True to disable this
    #: behavior and ignore CTRL-C instead.
    ignore_interrupt = False

    def __init__(self):
        if self.parent is not None:
            raise RuntimeError('Hub must be created in the root fiber')
        super(Hub, self).__init__(target=self.run)
        self.name = 'Hub'
        self.context = ''
        self._loop = pyuv.Loop()
        self._loop.excepthook = self._uncaught_exception
        self._data = {}
        self._noswitch_depth = 0
        self._callbacks = collections.deque()
        # Thread IDs may be recycled when a thread exits. But as long as the
        # hub is alive, it won't be recycled so in that case we can use just
        # the ID as a check whether we are in the same thread or not.
        self._thread = compat.get_thread_ident()
        self._async = pyuv.Async(self._loop, lambda h: self._loop.stop())
        self._sigint = pyuv.Signal(self._loop)
        self._sigint.start(self._on_sigint, signal.SIGINT)
        # Mark our own handles as "system handles". This allows the test suite
        # to check that no active handles except these escape from tests.
        self._async._system_handle = True
        self._sigint._system_handle = True
        self._log = logging.get_logger()
        self._log.debug('new Hub for {.name}', threading.current_thread())
        self._closing = False
        self._error = None
        self._poll = Poller(self)

    @property
    def loop(self):
        """The event loop used by this hub instance. This is an instance of
        :class:`pyuv.Loop`."""
        return self._loop

    @property
    def data(self):
        """A per-hub dictionary that can be used by applications to store data.

        Keys starting with ``'gruvi:'`` are reserved for internal use."""
        return self._data

    @property
    def poll(self):
        """A centrally managed poller that can be used install callbacks for
        file descriptor readiness events."""
        return self._poll

    def _on_sigint(self, h, signo):
        # SIGINT handler. Terminate the hub and switch back to the root, where
        # a KeyboardInterrupt will be raised.
        if self.ignore_interrupt:
            self._log.debug('SIGINT received, ignoring')
            return
        self._log.debug('SIGINT received, delivering as KeyboardInterrupt')
        self._error = KeyboardInterrupt('CTRL-C pressed')
        self.close()

    def _stop_loop(self):
        # Interrupt the event loop
        if compat.get_thread_ident() == self._thread:
            self._loop.stop()
        else:
            self._async.send()

    def _uncaught_exception(self, *exc_info):
        # Installed as the handler for uncaught exceptions in pyuv callbacks.
        # The exception is cleared by pyuv when this method is called. So we
        # have to format *exc_info ourselves, we cannot use _log.exception().
        self._log.error('uncaught exception in pyuv callback')
        trace = '\n'.join(traceback.format_exception(*exc_info))
        self._log.error('Traceback (most recent call last):\n{}', trace)

    def close(self):
        """Close the hub.

        This sets a flag that will cause the event loop to exit when it next
        runs. The hub fiber will then exit and control is transferred back to
        the root fiber.
        """
        if self._loop is None:
            return
        self._closing = True
        self._poll.close()
        self._stop_loop()

    def run(self):
        # Target of Hub.switch().
        if self.current() is not self:
            raise RuntimeError('run() may only be called from the Hub')
        self._log.debug('starting hub fiber')
        # This is where the loop is running.
        while True:
            self._run_callbacks()
            if self._closing:
                break
            mode = pyuv.UV_RUN_NOWAIT if len(self._callbacks) else pyuv.UV_RUN_DEFAULT
            with assert_no_switchpoints(self):
                self._loop.run(mode)
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
        self._async = None
        self._sigint = None
        self._log.debug('hub fiber terminated')
        if self._error:
            raise compat.saved_exc(self._error)

    def switch(self):
        """Switch to the hub.

        This method pauses the current fiber and runs the event loop. The
        caller should ensure that it has set up appropriate callbacks so that
        it will get scheduled again, preferably using :class:`switch_back`. In
        this case then return value of this method will be an ``(args,
        kwargs)`` tuple containing the arguments passed to the switch back
        instance.

        If this method is called from the root fiber then there are two
        additional cases. If the hub exited due to a call to :meth:`close`,
        then this method returns None. And if the hub exited due to a
        exception, that exception is re-raised here.
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
                self._log.exception('Ignoring exception in callback:')

    def run_callback(self, callback, *args):
        """Queue a callback.

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
        self._stop_loop()


@switchpoint
def sleep(secs):
    """Sleep for *secs* seconds. The *secs* argument can be an int or a float."""
    hub = get_hub()
    try:
        with switch_back(secs):
            hub.switch()
    except Timeout:
        pass
