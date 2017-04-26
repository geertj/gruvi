#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
The :mod:`gruvi.dbus` module implements a D-BUS client and server.

The implementation uses parts of the `txdbus
<https://github.com/cocagne/txdbus>`_ project. A cut down copy of txdbus,
containing only those parts needed by Gruvi, is available as ``gruvi.txdbus``.
You need this if you are providing a message handler (see below).

Both a client and a server/bus-side implementation are provided. The bus-side
implementation is very bare bones and apart from the "Hello" message it does
not implement any of the "org.freedestkop.DBus" interface. It also does not
implement any message routing. The server side is provided mostly for testing
purposes (but it could serve as the basis for a real D-BUS server).

The client side of a D-BUS connection is implemented by :class:`DbusClient` and
the server/bus-side by :class:`DbusServer`. Both implement a procedural
interface. Messages can be send using e.g. :meth:`DbusClient.send_message` or
:meth:`DbusClient.call_method`. An object-oriented interface that represents
D-BUS objects as Python objects, like the one txdbus provides, is currently not
available. The procedural interface can be used as a basis for your own
object-oriented interface though.

To receive notifications or to respond to method calls, you need to provide a
*message handler* to the client or the server constructor. The signature of the
message handler is: ``message_handler(message, protocol)``. Here, the *message*
argument is an instance of ``gruvi.txdbus.DbusMessages``, and the
*protocol* will be the :class:`DbusProtocol` instance for the current
connection.

Message handlers runs in their own fiber, which allows them to call into
switchpoints. There is one fiber for every connection.

Usage example::

  client = gruvi.DbusClient()
  client.connect('session')
  result = client.call_method('org.freedesktop.DBus', '/org/freedesktop/DBus',
                              'org.freedesktop.DBus', 'ListNames')
  for name in result[0]:
      print('Name: {}'.format(name))
"""

from __future__ import absolute_import, print_function

import os
import struct
import binascii
import codecs
import functools
import six
import pyuv

from . import compat
from .hub import switchpoint, switch_back
from .util import delegate_method
from .sync import Event
from .transports import TransportError
from .protocols import ProtocolError, MessageProtocol
from .stream import Stream
from .endpoints import Client, Server
from .address import saddr
from .vendor import txdbus

__all__ = ['DbusError', 'DbusMethodCallError', 'DbusProtocol', 'DbusClient', 'DbusServer']


class DbusError(ProtocolError):
    """Exception that is raised in case of D-BUS protocol errors."""


class DbusMethodCallError(DbusError):
    """Exception that is raised when a error reply is received for a D-BUS
    method call."""

    def __init__(self, method, reply):
        message = 'error calling {!r} method ({})'.format(method, reply.error_name)
        super(DbusMethodCallError, self).__init__(message)
        self._error = reply.error_name
        self._args = tuple(reply.body) if reply.body else ()

    @property
    def error(self):
        return self._error

    @property
    def args(self):
        return self._args


def parse_dbus_address(address):
    """Parse a D-BUS address string into a list of addresses."""
    if address == 'session':
        address = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
        if not address:
            raise ValueError('$DBUS_SESSION_BUS_ADDRESS not set')
    elif address == 'system':
        address = os.environ.get('DBUS_SYSTEM_BUS_ADDRESS',
                                 'unix:path=/var/run/dbus/system_bus_socket')
    addresses = []
    for addr in address.split(';'):
        p1 = addr.find(':')
        if p1 == -1:
            raise ValueError('illegal address string: {}'.format(addr))
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
            raise ValueError('unknown transport: {}'.format(kind))
        addresses.append(addr)
    return addresses


class TxdbusAuthenticator(object):
    """A adapter to use the txdbus client and server authenticators with our
    transports and protocols."""

    # For testing, cookie_dir is set to a temporary path. Otherwise, txdbus
    # uses ~/.dbus-keyrings as specified in the spec.
    cookie_dir = None

    def __init__(self, transport, server_side, server_guid=None):
        self._transport = transport
        self._server_side = server_side
        if self._server_side:
            self._authenticator = txdbus.BusAuthenticator(server_guid)
            self._authenticator.authenticators['DBUS_COOKIE_SHA1'].keyring_dir = self.cookie_dir
        else:
            self._authenticator = txdbus.ClientAuthenticator()
            self._authenticator.cookie_dir = self.cookie_dir
        self._authenticator.beginAuthentication(self)

    def sendAuthMessage(self, message):
        # Called by the txdbus authenticators
        message = message.encode('ascii') + b'\r\n'
        self._transport.write(message)

    @property
    def _unix_creds(self):
        # Used by txdbus.BusExternalAuthenticator
        return self._transport.get_extra_info('unix_creds')

    def handleAuthMessage(self, line):
        # Called by our protocol
        self._authenticator.handleAuthMessage(line)

    def authenticationSucceeded(self):
        """Return whether the authentication succeeded."""
        return self._authenticator.authenticationSucceeded()

    def getMechanismName(self):
        """Return the authentication mechanism name."""
        if self._server_side:
            mech = self._authenticator.current_mech
            return mech.getMechanismName() if mech else None
        else:
            return getattr(self._authenticator, 'authMech', None)

    def getUserName(self):
        """Return the authenticated user name (server side)."""
        if not self._server_side:
            return
        mech = self._authenticator.current_mech
        return mech.getUserName() if mech else None

    def getGUID(self):
        """Return the GUID of the authenticated server."""
        return self._authenticator.getGUID()


def parse_dbus_header(header):
    """Parse a D-BUS header. Return the message size."""
    if six.indexbytes(header, 0) == ord('l'):
        endian = '<'
    elif six.indexbytes(header, 0) == ord('B'):
        endian = '>'
    else:
        raise ValueError('illegal endianness')
    if not 1 <= six.indexbytes(header, 1) <= 4:
        raise ValueError('illegel message type')
    if struct.unpack(endian + 'I', header[8:12])[0] == 0:
        raise ValueError('illegal serial number')
    harrlen = struct.unpack(endian + 'I', header[12:16])[0]
    padlen = (8 - harrlen) % 8
    bodylen = struct.unpack(endian + 'I', header[4:8])[0]
    return 16 + harrlen + padlen + bodylen


def new_server_guid():
    """Return a new GUID for a server."""
    return binascii.hexlify(os.urandom(16)).decode('ascii')


class DbusProtocol(MessageProtocol):
    """D-BUS Protocol."""

    # According to the D-BUS spec the max message size is 128MB. However since
    # we want to limited memory usage we are much more conservative here.
    max_message_size = 128*1024

    # Maximum size for an authentication line
    max_line_size = 1000

    _next_unique_name = 0

    S_CREDS_BYTE, S_AUTHENTICATE, S_MESSAGE_HEADER, S_MESSAGE = range(4)

    def __init__(self, message_handler=None, server_side=False, server_guid=None, timeout=None):
        super(DbusProtocol, self).__init__(message_handler, timeout=timeout)
        self._server_side = server_side
        self._name_acquired = Event()
        self._buffer = bytearray()
        self._method_calls = {}
        self._authenticator = None
        if self._server_side:
            self._server_guid = server_guid or new_server_guid()
            self._unique_name = ':{}'.format(self._next_unique_name)
            type(self)._next_unique_name += 1
        else:
            self._server_guid = None
            self._unique_name = None
        self._state = None

    @property
    def server_guid(self):
        return self._server_guid

    def connection_made(self, transport):
        # Protocol callback
        super(DbusProtocol, self).connection_made(transport)
        # The client initiates by sending a '\0' byte, as per the D-BUS spec.
        if self._server_side:
            self._state = self.S_CREDS_BYTE
        else:
            self._state = self.S_AUTHENTICATE
            self._transport.write(b'\0')
        self._writer = Stream(transport, 'w')
        self._authenticator = TxdbusAuthenticator(transport, self._server_side, self._server_guid)
        self._message_size = 0

    def connection_lost(self, exc):
        # Protocol callback
        super(DbusProtocol, self).connection_lost(exc)
        if self._error is None:
            self._error = TransportError('connection lost')
        for notify in self._method_calls.values():
            if isinstance(notify, switch_back):
                notify.throw(self._error)
        self._method_calls.clear()
        self._name_acquired.set()
        self._authenticator = None  # break cycle

    def on_creds_byte(self, byte):
        if byte != 0:
            self._error = DbusError('first byte needs to be zero')
            return False
        self._state = self.S_AUTHENTICATE
        return True

    def on_partial_auth_line(self, line):
        if len(line) > self.max_line_size:
            self._error = DbusError('auth line too long ({} bytes)'.format(len(line)))
            return False
        return True

    def on_auth_line(self, line):
        if not self.on_partial_auth_line(line):
            return False
        if line[-2:] != b'\r\n':
            self._error = DbusError('auth line does not end with \\r\\n')
            return False
        try:
            line = codecs.decode(line[:-2], 'ascii')  # codecs.decode allows memoryview
        except UnicodeDecodeError as e:
            self._error = DbusError('auth line contain non-ascii chars')
            return False
        try:
            self._authenticator.handleAuthMessage(line)
        except txdbus.DBusAuthenticationFailed as e:
            self._error = DbusError('authentication failed: {!s}'.format(e))
            return False
        if self._authenticator.authenticationSucceeded():
            if not self._server_side:
                message = txdbus.MethodCallMessage('/org/freedesktop/DBus', 'Hello',
                                    'org.freedesktop.DBus', 'org.freedesktop.DBus')
                self._transport.write(message.rawMessage)
                self._method_calls[message.serial] = self.on_hello_response
            self._state = self.S_MESSAGE_HEADER
            self._server_guid = self._authenticator.getGUID()
        return True

    def on_hello_response(self, message):
        self._unique_name = message.body[0]
        self._name_acquired.set()

    def on_message_header(self, header):
        try:
            size = parse_dbus_header(header)
        except ValueError:
            self._error = DbusError('invalid message header')
            return False
        if size > self.max_message_size:
            self._error = DbusError('message too large ({} bytes)'.format(size))
            return False
        self._message_size = size
        self._state = self.S_MESSAGE
        return True

    def on_message(self, message):
        try:
            parsed = txdbus.parseMessage(message)
        except (txdbus.MarshallingError, struct.error) as e:
            self._error = DbusError('parseMessage() error: {!s}'.format(e))
            return False
        if self._server_side and not self._name_acquired.is_set():
            if isinstance(parsed, txdbus.MethodCallMessage) \
                        and parsed.member == 'Hello' \
                        and parsed.path == '/org/freedesktop/DBus' \
                        and parsed.interface == 'org.freedesktop.DBus' \
                        and parsed.destination == 'org.freedesktop.DBus':
                response = txdbus.MethodReturnMessage(parsed.serial, signature='s',
                                                      body=[self._unique_name])
                self._name_acquired.set()
                self._transport.write(response.rawMessage)
            else:
                self._error = DbusError('Hello method not called')
                return False
        elif isinstance(parsed, (txdbus.MethodReturnMessage, txdbus.ErrorMessage)) \
                    and getattr(parsed, 'reply_serial', 0) in self._method_calls:
            notify = self._method_calls.pop(parsed.reply_serial)
            notify(parsed)
        elif self._dispatcher:
            self._queue.put_nowait(parsed)
        else:
            mtype = type(parsed).__name__[:-7].lower()
            info = ' {!r}'.format(getattr(parsed, 'member', getattr(parsed, 'error_name', '')))
            self._log.warning('no handler, ignoring inbound {}{}', mtype, info)
        self._state = self.S_MESSAGE_HEADER
        return True

    def prepend_buffer(self, buf):
        if self._buffer:
            self._buffer.extend(buf)
            buf = self._buffer
            self._buffer = bytearray()
        return memoryview(buf)

    def data_received(self, data):
        view = memoryview(data)
        offset = 0
        while offset != len(data):
            if self._state == self.S_CREDS_BYTE:
                credsbyte = six.indexbytes(view, offset)
                offset += 1
                if not self.on_creds_byte(credsbyte):
                    break
            if self._state == self.S_AUTHENTICATE:
                pos = data.find(b'\n', offset)
                if pos == -1:
                    self._buffer.extend(view[offset:])
                    self.on_partial_auth_line(self._buffer)
                    break
                line = self.prepend_buffer(view[offset:pos+1])
                offset = pos+1
                if not self.on_auth_line(line):
                    break
            if self._state == self.S_MESSAGE_HEADER:
                needbytes = 16 - len(self._buffer)
                if len(data) - offset < needbytes:
                    self._buffer.extend(view[offset:])
                    break
                header = self.prepend_buffer(view[offset:offset+needbytes])
                if not self.on_message_header(header):
                    break
                offset += len(header)
                self._buffer.extend(header)
            if self._state == self.S_MESSAGE:
                needbytes = self._message_size - len(self._buffer)
                if len(data) - offset < needbytes:
                    self._buffer.extend(view[offset:])
                    break
                message = self.prepend_buffer(view[offset:offset+needbytes])
                offset += needbytes
                if not self.on_message(message):
                    break
        self._maybe_pause_transport()
        if self._error:
            self._transport.close()
            return

    @switchpoint
    def get_unique_name(self):
        """Return the unique name of the D-BUS connection."""
        self._name_acquired.wait()
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._transport is None:
            raise DbusError('not connected')
        return self._unique_name

    @switchpoint
    def send_message(self, message):
        """Send a D-BUS message.

        The *message* argument must be ``gruvi.txdbus.DbusMessage`` instance.
        """
        if not isinstance(message, txdbus.DbusMessage):
            raise TypeError('message: expecting DbusMessage instance (got {!r})',
                                type(message).__name__)
        self._name_acquired.wait()
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._transport is None:
            raise DbusError('not connected')
        self._writer.write(message.rawMessage)

    @switchpoint
    def call_method(self, service, path, interface, method, signature=None,
                    args=None, no_reply=False, auto_start=False, timeout=-1):
        """Call a D-BUS method and wait for its reply.

        This method calls the D-BUS method with name *method* that resides on
        the object at bus address *service*, at path *path*, on interface
        *interface*.

        The *signature* and *args* are optional arguments that can be used to
        add parameters to the method call. The signature is a D-BUS signature
        string, while *args* must be a sequence of python types that can be
        converted into the types specified by the signature. See the `D-BUS
        specification
        <http://dbus.freedesktop.org/doc/dbus-specification.html>`_ for a
        reference on signature strings.

        The flags *no_reply* and *auto_start* control the NO_REPLY_EXPECTED and
        NO_AUTO_START flags on the D-BUS message.

        The return value is the result of the D-BUS method call. This will be a
        possibly empty sequence of values.
        """
        message = txdbus.MethodCallMessage(path, method, interface=interface,
                                destination=service, signature=signature, body=args,
                                expectReply=not no_reply, autoStart=auto_start)
        serial = message.serial
        if timeout == -1:
            timeout = self._timeout
        try:
            with switch_back(timeout) as switcher:
                self._method_calls[serial] = switcher
                self.send_message(message)
                args, _ = self._hub.switch()
        finally:
            self._method_calls.pop(serial, None)
        response = args[0]
        assert response.reply_serial == serial
        if isinstance(response, txdbus.ErrorMessage):
            raise DbusMethodCallError(method, response)
        args = tuple(response.body) if response.body else ()
        return args


class DbusClient(Client):
    """A D-BUS client."""

    def __init__(self, message_handler=None, timeout=30):
        """
        The *message_handler* argument specifies an optional message handler.

        The optional *timeout* argument specifies a default timeout for
        protocol operations in seconds.
        """
        protocol_factory = functools.partial(DbusProtocol, message_handler)
        super(DbusClient, self).__init__(protocol_factory, timeout)

    @switchpoint
    def connect(self, address='session'):
        """Connect to *address* and wait until the connection is established.

        The *address* argument must be a D-BUS server address, in the format
        described in the D-BUS specification. It may also be one of the special
        addresses ``'session'`` or ``'system'``, to connect to the D-BUS
        session and system bus, respectively.
        """
        if isinstance(address, six.string_types):
            addresses = parse_dbus_address(address)
        else:
            addresses = [address]
        for addr in addresses:
            try:
                super(DbusClient, self).connect(addr)
            except pyuv.error.UVError:
                continue
            break
        else:
            raise DbusError('could not connect to any address')
        # Wait for authentication to complete
        self.get_unique_name()

    protocol = Client.protocol

    delegate_method(protocol, DbusProtocol.get_unique_name)
    delegate_method(protocol, DbusProtocol.send_message)
    delegate_method(protocol, DbusProtocol.call_method)


class DbusServer(Server):
    """A D-BUS server."""

    def __init__(self, message_handler, timeout=30):
        """
        The *message_handler* argument specifies the message handler.

        The optional *timeout* argument specifies a default timeout for
        protocol operations in seconds.
        """
        protocol_factory = functools.partial(DbusProtocol, message_handler,
                                             server_side=True)
        super(DbusServer, self).__init__(protocol_factory, timeout)

    @switchpoint
    def listen(self, address='session'):
        """Start listening on *address* for new connection.

        The *address* argument must be a D-BUS server address, in the format
        described in the D-BUS specification. It may also be one of the special
        addresses ``'session'`` or ``'system'``, to connect to the D-BUS
        session and system bus, respectively.
        """
        if isinstance(address, six.string_types):
            addresses = parse_dbus_address(address)
        else:
            addresses = [address]
        for addr in addresses:
            try:
                super(DbusServer, self).listen(addr)
            except pyuv.error.UVError:
                self._log.error('skipping address {}', saddr(addr))
