#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from . import logging
from .sync import Queue
from .errors import Error
from .hub import get_hub
from .fibers import spawn

__all__ = ['ProtocolError', 'BaseProtocol', 'Protocol', 'DatagramProtocol',
           'MessageProtocol']


class ProtocolError(Error):
    """A protocol error."""


class BaseProtocol(object):
    """Base class for all protocols."""

    def __init__(self, timeout=None):
        """The *timeout* argument specifies a default timeout for various
        protocol operations."""
        self._timeout = timeout
        self._log = logging.get_logger()
        self._error = None

    def connection_made(self, transport):
        """Called when a connection is made."""

    def connection_lost(self, exc):
        """Called when a connection is lost."""

    def pause_writing(self):
        """Called when the write buffer in the transport has exceeded the high
        water mark. The protocol should stop writing new data."""

    def resume_writing(self):
        """Called when the write buffer in the transport has fallen below the
        low water mark. The protocol can start writing data again."""


class Protocol(BaseProtocol):
    """Base class for connection oriented protocols."""

    def data_received(self, data):
        """Called when a new chunk of data is received."""

    def eof_received(self):
        """Called when an EOF is received."""


class DatagramProtocol(BaseProtocol):
    """Base classs for datagram oriented protocols."""

    def datagram_received(self, data, addr):
        """Called when a new datagram is received."""

    def error_received(self, exc):
        """Called when an error has occurred."""


class MessageProtocol(Protocol):
    """Base class for message oriented protocols."""

    max_queue_size = 10

    def __init__(self, message_handler=None, timeout=None):
        super(MessageProtocol, self).__init__(timeout=timeout)
        self._message_handler = message_handler
        self._hub = get_hub()
        self._queue = Queue()
        self._dispatcher = None

    def _maybe_pause_transport(self):
        # Stop transport from calling data_received() if queue is at capacity
        if self._queue.qsize() >= self.max_queue_size:
            self._transport.pause_reading()

    def _maybe_resume_transport(self):
        # Resume data_received if queue has room.
        if self._queue.qsize() < self.max_queue_size:
            self._transport.resume_reading()

    def _dispatch_loop(self):
        # Call message handler for HTTP requests. Runs in a separate fiber.
        self._log.debug('dispatcher starting')
        try:
            while True:
                message = self._queue.get()
                if self._transport is None:
                    break
                self._maybe_resume_transport()
                self._message_handler(message, self._transport, self)
        finally:
            self._log.debug('dispatcher exiting, closing transport')
            if self._transport is not None:
                self._transport.close()

    def connection_made(self, transport):
        # Protocol callback
        self._transport = transport
        if self._message_handler:
            self._dispatcher = spawn(self._dispatch_loop)

    def connection_lost(self, exc):
        # Protocol callback
        if self._dispatcher:
            self._dispatcher.cancel()
        self._transport = None
