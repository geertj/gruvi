#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import socket
import _ssl
import ssl
import six

__all__ = []

if sys.version_info[:2] < (3, 5):
    from . import _sslcompat

    # Export constants from _sslcompat
    for key in dir(_sslcompat):
        if key[:4].isupper():  # also export FOO_BARv1
            value = getattr(_sslcompat, key)
            globals()[key] = value
    errorcode = _sslcompat.errorcode

if hasattr(ssl, 'CHANNEL_BINDING_TYPES'):
    CHANNEL_BINDING_TYPES = ssl.CHANNEL_BINDING_TYPES
elif _sslcompat.HAS_TLS_UNIQUE:
    CHANNEL_BINDING_TYPES = ['tls-unique']
else:
    CHANNEL_BINDING_TYPES = []

if hasattr(ssl, 'MemoryBIO'):
    MemoryBIO = ssl.MemoryBIO
else:
    MemoryBIO = _sslcompat.MemoryBIO


if hasattr(ssl, 'SSLContext'):

    # Python 2.7.9 and Python 3.x

    SSLContext = ssl.SSLContext

else:

    # Python 2.7.x, x <= 8

    class SSLContext(object):

        # This isn't a real SSLContext so it doesn't do things like session
        # caching. The purpose is to store arguments to :func:`ssl.wrap_socket`
        # in a way that is compatible with Py3k.

        def __init__(self, protocol):
            # [keyfile, certfile, cert_reqs, ssl_version, ca_certs, ciphers]
            self._ssl_args = [None, None, ssl.CERT_NONE, protocol, None, ssl._DEFAULT_CIPHERS]
            # Implement the same defaults as the Python ssl module
            self._options = _sslcompat.OP_ALL & _sslcompat.OP_NO_SSLv2
            self._dh_params = None

        @property
        def protocol(self):
            return self._ssl_args[3]

        @property
        def verify_mode(self):
            return self._ssl_args[2]

        @verify_mode.setter
        def verify_mode(self, cert_reqs):
            self._ssl_args[2] = cert_reqs

        @property
        def options(self):
            return self._options

        @options.setter
        def options(self, options):
            self._options = options

        def load_verify_locations(self, ca_certs):
            self._ssl_args[4] = ca_certs

        def load_cert_chain(self, certfile, keyfile):
            self._ssl_args[0] = keyfile
            self._ssl_args[1] = certfile

        def set_ciphers(self, ciphers):
            self._ssl_args[5] = ciphers

        def load_dh_params(self, dh_params):
            self._dh_params = dh_params


if hasattr('ssl', 'SSLObject'):

    # Python 3.5

    SSLObject = ssl.SSLObject

else:

    # Python 2.7, 3.3 and 3.4
    # SSLObject was copied and adapted from Python 3.5

    class SSLObject(object):
        """An :class:`ssl.SSLObject` implementation for Python 2.7, 3.3 and 3.4."""

        def __init__(self, sslobj, sslctx, server_side, server_hostname):
            self._sslobj = sslobj
            self._sslctx = sslctx
            self._server_side = server_side
            self._server_hostname = server_hostname

        @property
        def context(self):
            return self._sslctx

        @context.setter
        def context(self, ctx):
            if not hasattr(self._sslobj, 'context'):
                raise RuntimeError('cannot set context on Python 2.7')
            self._sslobj.context = ctx
            self._sslctx = ctx

        @property
        def server_side(self):
            return self._server_side

        @property
        def server_hostname(self):
            return self._server_hostname

        def read(self, len=0, buffer=None):
            if buffer is not None:
                v = self._sslobj.read(len, buffer)
            else:
                v = self._sslobj.read(len or 1024)
            return v

        def write(self, data):
            return self._sslobj.write(data)

        def getpeercert(self, binary_form=False):
            return self._sslobj.peer_certificate(binary_form)

        def selected_npn_protocol(self):
            if hasattr(self._sslobj, 'selected_npn_protocol'):
                return self._sslobj.selected_npn_protocol()

        def cipher(self):
            return self._sslobj.cipher()

        def compression(self):
            if hasattr(self._sslobj, 'compression'):
                return self._sslobj.compression()
            else:
                return _sslcompat.compression(self._sslobj)

        def pending(self):
            return self._sslobj.pending()

        def do_handshake(self, block=False):
            self._sslobj.do_handshake()
            if getattr(self.context, 'check_hostname', False):
                if not self.server_hostname:
                    raise ValueError('check_hostname needs server_hostname argument')
                ssl.match_hostname(self.getpeercert(), self.server_hostname)

        def unwrap(self):
            self._sslobj.shutdown()

        def get_channel_binding(self, cb_type="tls-unique"):
            if cb_type not in CHANNEL_BINDING_TYPES:
                raise ValueError('Unsupported channel binding type')
            if cb_type != 'tls-unique':
                raise NotImplementedError('{0} channel binding not implemented'.format(cb_type))
            if hasattr(self._sslobj, 'tls_unique_cb'):
                return self._sslobj.tls_unique_cb()
            else:
                return _sslcompat.tls_unique_cb(self._sslobj)


def get_dummy_socket():
    # Return a dummy socket that can be wrapped by _ssl.
    sock = socket.socket()
    if six.PY2:
        sock = sock._sock
    sock.setblocking(False)
    return sock

_sock = None


def wrap_bio(ctx, incoming, outgoing, server_side=False, server_hostname=None):
    """Create a new SSL protocol instance from a context and a BIO pair."""
    if hasattr(ctx, 'wrap_bio'):
        # Python 3.5
        return ctx.wrap_bio(incoming, outgoing, server_side, server_hostname)
    # Allocate a single global dummy socket to wrap on Python < 3.5
    global _sock
    if _sock is None:
        _sock = get_dummy_socket()
    if hasattr(ctx, '_wrap_socket'):
        # Python 2.7.9+, Python 3.x
        sslobj = ctx._wrap_socket(_sock, server_side, server_hostname)
    else:
        # Python 2.7.x, x <= 8
        #
        # We need to do some magic to support anonymous DH authentication. Anon
        # DH doesn't need a certfile and a keyfile, but the Python 2.x
        # _ssl.sslwrap raises an exception if these are absent for server side
        # sockets. So the workaround is to create the socket as a client-side
        # socket and then flip it afterwards if needed.
        sslobj = _ssl.sslwrap(_sock, False, *ctx._ssl_args)
        if ctx._dh_params:
            _sslcompat.load_dh_params(sslobj, ctx._dh_params)
        if server_side:
            _sslcompat.set_accept_state(sslobj)
        _sslcompat.set_options(sslobj, ctx._options)
        if server_hostname:
            _sslcompat.set_tlsext_host_name(server_hostname)
    _sslcompat.set_bio(sslobj, incoming, outgoing)
    pyobj = SSLObject(sslobj, ctx, server_side, server_hostname)
    return pyobj


def get_reason(exc):
    """Return the reason code from an SSLError exception."""
    # On Python 3.x the reason is available via exc.reason.
    if hasattr(exc, 'reason'):
        return exc.reason
    # .. but on 2.x we have to parse the error string (fortunately it is there)
    message = exc.args[1]
    p0 = message.find('error:')
    if p0 == -1:
        return
    p0 += 6
    p1 = message.find(':', p0)
    assert p1 != -1
    code = int(message[p0:p1], 16) & 0xfff
    return errorcode.get(code)
