#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2012 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import pyuv
import greenlet


class Greenlet(greenlet.greenlet):

    def __init__(self, hub):
        super(Greenlet, self).__init__(parent=hub)
        self.hub = hub
        # XXX: keep a reference to us in Hub due to a bug
        # in pyuv reference counting
        self.hub.greenlets.add(self)
        self.handles = []

    def start(self, target=None, *args):
        """Start the greenlet. The greenlet will be switched to by the Hub
        the next time it runs.
        """
        self.target = target
        self.args = args
        self.start_handle = pyuv.Prepare(self.hub.loop)
        self.start_handle.start(self._start)
        self.stop_handle = pyuv.Prepare(self.hub.loop)
        self.stop_handle.start(self._stop)

    def _start(self, handle):
        """Start the greenlet."""
        handle.close()
        self.switch(*self.args)

    def _stop(self, handle):
        """Drop our reference to the loop when this greenlet exits."""
        if self.dead:
            handle.close()
            self.hub.greenlets.remove(self)

    def switch(self, *args):
        """Switch to this greenlet."""
        current = greenlet.getcurrent()
        if current is not self.hub:
            raise RuntimeError('only the Hub may switch() to a greenlet')
        super(Greenlet, self).switch(*args)

    def run(self, *args):
        """Worker"""
        if self.target is not None:
            self.target(*args)
