#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
This module implements a D-BUS client.

The implementation uses Tom Cocagne's excellent `txdbus
<https://github.com/cocagne/txdbus>`_ for marshalling and demarshalling
messages. A cut down copy of it, containing only the functionality needed by
Gruvi, is available as :mod:`gruvi.txdbus`. You need this if you are providing
a message handler (see below).

Currently only a client is implemented. The missing piece for a server
implementation is the server-side authentication mechanism.

The D-BUS client can react to incoming messages by providing a message handler
to the constructor. This message handler will be called for incoming messages
that are not replies to method calls made with :meth:`DBusClient.call_method`.

The signature of the message handler is: ``message_handler(message, protocol,
client)``. Here, the *message* argument is an instance of a subclass of
:class:`txdbus.DBusMessage`. The *protocol* will always be the DBusClient
instance since currently there is no DBusServer. The *client* will be the
transport this message was received on, which will currently always be
:attr:`DBusClient.transport`. 

The return value of the message handler may be ``None``, or an instance of a
:class:`txdbus.DBusMessage` subclass. The latter is useful when you are
responding to a method call.

Message handlers runs in their own fiber. This allows a message handler to call
into a switchpoint. There will be one fiber for every transport.
"""

from __future__ import absolute_import, print_function

import os
import struct

from . import hub, error, txdbus, protocols, dbus_ffi, compat
from .hub import switchpoint
from .util import objref
from .protocols import errno, ProtocolError

__all__ = ['DBusError', 'DBusClient']


class DBusError(ProtocolError):
    """Exception that is raised in case of D-BUS protocol errors."""


class DBusClientAuthenticator(object):
    """A client-side D-BUS authenticator."""

    # Currently this only supports the EXTERNAL mechanism. EXTERNAL works for
    # any type of local sockets except TCP sockets on Windows. In real life
    # this should not be a limitation, at least not for now.

    s_start, s_auth_external, s_authenticated, s_failed = range(4)

    def __init__(self):
        self._state = self.s_start
        self._username = b''

    @property
    def username(self):
        return self._username

    def feed(self, line):
        """Feed *line* into the authenticator. Return authentication data that
        must be sent to the remote peer."""
        if self._state == self.s_authenticated:
            return b''
        elif self._state == self.s_failed:
            raise ValueError('authentication failed')
        if self._state == self.s_start:
            if line:
                raise ValueError('client must initiate handshake')
            self._state = self.s_auth_external
            return b'\0AUTH EXTERNAL\r\n'
        if not line.endswith(b'\r\n'):
            raise ValueError('Incomplete line')
        pos = line.find(b' ')
        if pos != -1:
            command = line[:pos]
            args = line[pos+1:-2]
        else:
            command = line[:-2]
            args = b''
        if command == b'OK':
            self._state = self.s_authenticated
            self._username = '<external>'
            return b'BEGIN\r\n'
        elif command == b'REJECTED':
            self._state = self.s_failed
            raise ValueError('authentication failed')
        elif command == b'DATA':
            return b'DATA\r\n'
        else:
            self._state = self.s_failed
            raise ValueError('unexpected command {0!r}'.format(command))


class DBusParser(protocols.Parser):
    """A D-BUS message parser."""

    # According to the D-BUS spec the max message size is 128MB. However since
    # we want to limited memory usage we are much more conservative here.
    max_message_size = 128*1024

    def __init__(self):
        super(DBusParser, self).__init__()
        self._buffer = bytearray()
        self._context = dbus_ffi.ffi.new('struct context *')

    def feed(self, buf):
        # len(buf) == 0 means EOF received
        if len(buf) == 0:
            if len(self._buffer) > 0:
                self._error = errno.FRAMING_ERROR
                self._error_message = 'partial message'
                return -1
            return 0
        # "struct context" is a C object and does *not* take a reference
        # Therefore use a Python variable to keep the cdata object alive
        cdata = self._context.buf = dbus_ffi.ffi.new('char[]', buf)
        self._context.buflen = len(buf)
        offset = self._context.offset = 0
        while offset != len(buf):
            error = dbus_ffi.lib.split(self._context)
            if error and error != dbus_ffi.lib.INCOMPLETE:
                self._error = errno.FRAMING_ERROR
                self._error_message = 'dbus_ffi.split(): error {0}'.format(error)
                offset = self._context.offset
                break
            nbytes = self._context.offset - offset
            if len(self._buffer) + nbytes > self.max_message_size:
                self._error = errno.MESSAGE_TOO_LARGE
                self._offset = 0
                break
            if error == dbus_ffi.lib.INCOMPLETE:
                self._buffer.extend(buf[offset:])
                return
            chunk = buf[offset:self._context.offset]
            if self._buffer:
                self._buffer.extend(chunk)
                chunk = bytes(self._buffer)
                self._buffer = bytearray()
            try:
                message = txdbus.parseMessage(chunk)
            except (txdbus.MarshallingError, struct.error) as e:
                self._error = errno.PARSE_ERROR
                self._error_message = 'txdbus.parseMessage(): {0!s}'.format(e)
                offset = 0
                break
            self._messages.append(message)
            offset = self._context.offset
        return offset


def parse_dbus_address(address):
    """Parse a D-BUS address string into a list of addresses."""
    if address == 'session':
        address = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
        if not address:
            raise ValueError('$DBUS_SESSION_BUS_ADDRESS not set')
    elif address == 'system':
        address = os.environ.get('DBUS_SYSTEM_BUS_ADDRES',
                                'unix:path=/var/run/dbus/system_bus_socket')
    addresses = []
    for addr in address.split(';'):
        p1 = addr.find(':')
        if p1 == -1:
            raise ValueError('illegal address string: {0}'.formnat(addr))
        kind = addr[:p1]
        args = dict((kv.split('=') for kv in addr[p1+1:].split(',')))
        if kind == 'unix':
            if 'path' in args:
                addr = args['path']
            elif 'abstract' in args:
                addr = '\0' + args['abstract']
            else:
                raise ValueError('require "path" or "abstract" for unix')
        elif kind == 'tcp':
            if 'host' not in args or 'port' not in args:
                raise ValueError('require "host" and "port" for tcp')
            addr = (args['host'], int(args['port']))
        else:
            raise ValueError('unknown transport: {0}'.format(kind))
        addresses.append(addr)
    return addresses


class DBusBase(protocols.RequestResponseProtocol):

    _exception = DBusError
    _authenticator = None

    def __init__(self, message_handler=None, timeout=None):
        """The constructor accepts the following arguments. The
        *message_handler* argument specifies an optional message handler that
        can be used to react to inbound messages. See the notes at the top for
        more information on the message handler.

        The optional *timeout* argument can be used to specify a timeout for
        the various network operations used in the client.
        """
        super(DBusBase, self).__init__(DBusParser, timeout)
        self._message_handler = message_handler
        self._buffer = b''

    def _init_transport(self, transport):
        super(DBusBase, self)._init_transport(transport)
        transport._authenticator = self._authenticator()
        transport._authenticated = False
        transport._unique_name = None
        transport._queue._sizefunc = lambda msg: len(msg.rawMessage or b'')

    def _start_authentication(self, transport):
        authdata = transport._authenticator.feed(b'')
        assert authdata != b''
        transport.write(authdata)

    def _on_transport_readable(self, transport, data, error):
        if transport._authenticated or error:
            super(DBusBase, self)._on_transport_readable(transport, data, error)
            return
        # Handle authentication
        self._buffer += data
        pos = self._buffer.find(b'\r\n')
        if pos == -1:
            if len(self._buffer) > 1024:
                self._close_transport(transport)
            return
        line = self._buffer[:pos+2]
        self._buffer = self._buffer[pos+2:]
        try:
            authdata = transport._authenticator.feed(line)
        except ValueError as e:
            transport._log.error('authentication error: {!s}', e)
            error = DBusError(errno.AUTH_ERROR, str(e))
            self._close_transport(transport, error)
            return
        if authdata:
            transport.write(authdata)
        if transport._authenticator.username:
            transport._authenticated = True
            transport._events.emit('AuthenticationComplete')
            super(DBusBase, self)._on_transport_readable(transport,
                                        self._buffer, 0)
            self._buffer = b''

    def _dispatch_fast_path(self, transport, message):
        if isinstance(message, txdbus.MethodReturnMessage):
            event = 'MethodResponse:{0}'.format(message.reply_serial)
            if transport._events.emit(event, message):
                return True
        if not self._message_handler:
            transport._log.debug('no handler, dropping incoming message')
            return True
        return False
    
    def _dispatch_message(self, transport, message):
        """Dispatch a single message."""
        result = self._message_handler(message, self, transport)
        if result:
            self._write(transport, result.rawMessage)

    @switchpoint
    def _send_message(self, transport, message):
        if self._transport is None and not self._transport.closed:
            raise RuntimeError('not connected')
        if not isinstance(message, txdbus.DBusMessage):
            raise TypeError('expecting DBusMessage instance')
        self._write(transport, message.rawMessage)


class DBusClient(DBusBase):
    """A D-BUS client."""

    _authenticator = DBusClientAuthenticator

    @switchpoint
    def connect(self, address='session'):
        """Connect to *address* and wait until the connection is established.

        The *address* argument must be a D-BUS "server address", as explained
        in the `D-BUS specification
        <http://dbus.freedesktop.org/doc/dbus-specification.html>`_. It may
        also be one of the special addresses ``'session'`` or ``'system'``, to
        connect to the D-BUS session and system bus, respectively.
        """
        if isinstance(address, (compat.binary_type, compat.text_type)):
            addresses = parse_dbus_address(address)
        elif hasattr(address, 'connect'):
            addresses = [address]
        else:
            raise TypeError('address: expecting a string or a transport')
        for addr in addresses:
            try:
                self._connect(addr)
            except error.Error:
                continue
            break
        else:
            raise DBusError('could not connect to any address')
        self._start_authentication(self._transport)
        events = ('AuthenticationComplete', 'HandleError')
        self._transport._events.wait(self._timeout, waitfor=events)
        if self._transport._error:
            raise self._transport._error
        elif not self._transport._authenticated:
            raise DBusError(errno.TIMEOUT, 'timeout authenticating to the bus')
        unique_name = self.call_method('org.freedesktop.DBus',
                                       '/org/freedesktop/DBus',
                                       'org.freedesktop.DBus', 'Hello')
        self._transport._unique_name = unique_name

    def unique_name(self):
        """Return the unique bus name of the connection."""
        if self._transport is None or self._transport.closed:
            raise RuntimeError('not connected')
        return self._transport._unique_name

    @switchpoint
    def call_method(self, service, path, interface, method, signature=None,
                    args=None, no_reply=False, auto_start=False):
        """Call a D-BUS method and wait for its reply.

        This method calls the D-BUS method that resides on the object at bus
        address *service*, at path *path*, on interface *interface*.

        The *signature* and *args* are optional arguments that can be used to
        add parameters to the method call. The signature is a D-BUS signature
        string, while *args* must be a sequence of python types that can be
        converted into the types specified by the signature. See the `D-BUS
        specification
        <http://dbus.freedesktop.org/doc/dbus-specification.html>`_ for a
        reference on signature strings.

        The flags *no_reply* and *auto_start* control the NO_REPLY_EXPECTED and
        NO_AUTO_START flags on the D-BUS message.

        The return value is the result of the D-BUS method call, in the
        following way: if there were no values in the response, then None is
        returned. If there was one value in the response, then that value is
        returned. And if there were multiple values in the response then the
        values are returned in a list.
        """
        if self._transport is None or self._transport.closed:
            raise RuntimeError('not connected')
        message = txdbus.MethodCallMessage(path, method, interface=interface,
                                           destination=service,
                                           signature=signature, body=args,
                                           expectReply=not no_reply,
                                           autoStart=auto_start)
        self.send_message(message)
        events = ('MethodResponse:{0}'.format(message.serial), 'HandleError')
        response = self._transport._events.wait(self._timeout, waitfor=events)
        if response == 'HandleError':
            raise self._transport._error
        event, response = response
        assert isinstance(response, txdbus.DBusMessage)
        assert response.reply_serial == message.serial
        if isinstance(response, txdbus.ErrorMessage):
            raise DBusError(errno.REQUEST_ERROR, response)
        body = response.body
        if body is None or len(body) == 0:
            body = None
        elif len(body) == 1:
            body = body[0]
        return body

    @switchpoint
    def send_message(self, message):
        """Send a D-BUS message.

        The *message* argument must a valid :class:`txdbus.DBusMessage`
        instance.
        """
        self._send_message(self.transport, message)
