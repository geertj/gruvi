#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2012 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import

import pyuv
import greenlet


class Hub(greenlet.greenlet):
    """The Hub.

    This is our central scheduler that schedules between greenlets.

    Greenlets are cooperatively scheduled. When a greenlet needs to block on
    IO, it must use :meth:`wait()` to set up one or more wakeup conditions,
    and the it should :meth:`switch()` to the hup. When one of the wakeup
    conditions triggers, the greenlet will be scheduled again.
    """

    instance = None

    def __init__(self, loop=None):
        current = greenlet.getcurrent()
        if current.parent is not None:
            raise RuntimeError('Hub must be created in the root greenlet')
        super(Hub, self).__init__()
        self.loop = loop or pyuv.Loop.default_loop()
        self.greenlets = set()

    @classmethod
    def get(cls):
        """Return the singleton instance of the hub."""
        if cls.instance is None:
            cls.instance = Hub()
        return cls.instance

    def run(self):
        """Target of Hub.switch()."""
        current = greenlet.getcurrent()
        if current is not self:
            raise RuntimeError('run() may only be called from the Hub')
        while True:
            self.loop.run()
            self.parent.switch()

    def switch(self):
        """Switch to the hub. Can be called from the root greenlet to start the
        event loop, or from a non-root greenlet to wait for I/O. """
        current = greenlet.getcurrent()
        if current is self:
            raise RuntimeError('switch() may not be called from the Hub')
        super(Hub, self).switch()

    def switch_back(self):
        """Return a callback that switches back to the current greenlet."""
        current = greenlet.getcurrent()
        def callback(*args):
            current.switch(*args)
        return callback
