#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from . import logging, util
from .sync import Event, Queue
from .errors import Error, Cancelled
from .hub import get_hub
from .fibers import Fiber

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
        self._transport = None
        self._error = None

    def connection_made(self, transport):
        """Called when a connection is made."""
        self._transport = transport

    def connection_lost(self, exc):
        """Called when a connection is lost."""
        # Unblock everybody who might be waiting.
        if self._error is None:
            self._error = exc
        self._transport = None

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


class MessageProtocol(Protocol):
    """Base class for message oriented protocols."""

    def __init__(self, dispatch, timeout=None):
        """The *dispatch* argument controls whether a fiber is started that
        will call the :meth:`message_received` callback for incoming messages.

        The *timeout* argument specifies a default timeout for various protocol
        operations.
        """
        super(MessageProtocol, self).__init__(timeout=timeout)
        self._hub = get_hub()
        self._queue = Queue()
        if not dispatch:
            self._dispatcher = None
            return
        name = util.split_cap_words(type(self).__name__)[0]
        key = 'gruvi:next_{}_dispatcher'.format(name.lower())
        seq = self._hub.data.setdefault(key, 1)
        self._hub.data[key] += 1
        name = '{}-{}'.format(name, seq)
        self._dispatcher = Fiber(self._dispatch_loop, name=name)
        self._dispatcher.start()

    @property
    def queue(self):
        """A :class:`~gruvi.Queue` instance containing parsed messages."""
        return self._queue

    @property
    def dispatcher(self):
        """The dispatcher fiber, or None if there is no dispatcher."""
        return self._dispatcher

    def connection_lost(self, exc):
        # Protocol callback.
        # The connection is lost, which means that no requests that is either
        # outstanding or in-progress will be able to send output to the remote
        # peer. Therefore we just to discard everything here.
        super(MessageProtocol, self).connection_lost(exc)
        if self._dispatcher:
            self._dispatcher.cancel()
            self._dispatcher = None

    def message_received(self, message):
        """Called by the dispatcher fiber when a new message is added to the
        :attr:`queue`."""

    def _dispatch_loop(self):
        # Dispatcher loop: runs in a separate fiber and is only started
        # if dispatch=True in the constructor.
        self._log.debug('dispatcher starting')
        try:
            while True:
                message = self._queue.get()
                self.message_received(message)
        except Cancelled as e:
            self._log.debug('dispatcher was canceled')
        except ProtocolError as e:
            self._log.error('{!s}, closing connection', e)
            self._error = e
            self._transport.close()
        except Exception as e:
            self._log.exception('uncaught exception in dispatcher')
            self._error = ProtocolError('uncaught exception in dispatcher')
            self._transport.close()
        self._log.debug('dispatcher exiting')


class DatagramProtocol(BaseProtocol):
    """Base classs for datagram oriented protocols."""

    def datagram_received(self, data, addr):
        """Called when a new datagram is received."""

    def error_received(self, exc):
        """Called when an error has occurred."""
