#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import inspect
import greenlet
from . import hub, logging, util

__all__ = ['Greenlet']


class Greenlet(greenlet.greenlet):
    """An explicitly scheduled independent execution context aka *co-routine*.

    This class is a very thin layer on top of :class:`greenlet.greenlet` that
    adds a :meth:`start` method and enforces the requirement that only the hub
    may switch to greenlets. 

    All user created greenlets should use this interface. The only greenlets in
    a Gruvi application that use the "raw" :class:`greenlet.greenlet` interface
    are the root greenlet, and the :class:`Hub`.
    """

    def __init__(self, target, callback=None):
        self._hub = hub.get_hub()
        super(Greenlet, self).__init__(parent=self._hub)
        self._target = target
        self._logger = logging.get_logger(util.objref(self))
        self._callbacks = []
        if callback:
            self.notify(callback)

    @property
    def target(self):
        """The greenlet's target."""
        return self._target

    def start(self, *args):
        """Schedule the greenlet to be started in the next iteration of the
        event loop."""
        self._hub.run_callback(self.switch, *args)

    def switch(self, *args):
        """Switch to this greenlet.
        
        If this is the first time the greenlet is being switched to, its
        execution context is allocated.
        """
        current = greenlet.getcurrent()
        if current is not self._hub:
            raise RuntimeError('only the Hub may switch() to a greenlet')
        super(Greenlet, self).switch(*args)

    def run(self, *args):
        # Worker. This is the target of the first :meth:`switch()` call.
        if self._target is None:
            raise NotImplementedError('empty run() method')
        exc = None
        try:
            value = self._target(*args)
        except greenlet.GreenletExit as e:
            value = e
        except Exception as e:
            self._logger.exception('uncaught exception in greenlet')
            exc = e
        for callback in self._callbacks:
            self._hub.run_callback(callback, self, value, exc)

    def notify(self, callback):
        """Notify a callback when the greenlet exits."""
        self._callbacks.append(callback)

    def join(self):
        """Wait until the the greenlet exits."""
        current = greenlet.getcurrent()
        if current is self._hub:
            raise RuntimeError('you may not join() the Hub')
        if current.parent is None:
            raise RuntimeError('you may not join() the root greenlet')
        self.notify(self._hub.switch_back())
        self._hub.switch(timeout)
