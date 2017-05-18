#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
import socket
import _ssl
import ssl
import six

if sys.version_info[:2] < (3, 5):
    from . import _sslcompat

__all__ = ['create_default_context']


if hasattr(ssl, 'CertificateError'):
    # Python 2.7.9+ and Python 3.3+
    CertificateError = ssl.CertificateError

else:
    # Python 2.7.x, x <= 8
    CertificateError = ValueError


if hasattr(ssl, 'SSLContext'):
    # Python 2.7.9+ and Python 3.3+
    SSLContext = ssl.SSLContext

else:
    # Python 2.7.x, x <= 8

    class SSLContext(object):

        # This isn't a real SSLContext so it doesn't do things like session
        # caching. The purpose is to store keyword arguments to _ssl.sslwrap()
        # while having an external interfact that is a subset of the real SSLContext.

        def __init__(self, protocol=ssl.PROTOCOL_SSLv23):
            # [keyfile, certfile, cert_reqs, ssl_version, ca_certs, ciphers]
            self._sslwrap_args = [None, None, ssl.CERT_NONE, protocol, None, ssl._DEFAULT_CIPHERS]

        @property
        def protocol(self):
            return self._sslwrap_args[3]

        @property
        def verify_mode(self):
            return self._sslwrap_args[2]

        @verify_mode.setter
        def verify_mode(self, cert_reqs):
            self._sslwrap_args[2] = cert_reqs

        def load_verify_locations(self, ca_certs):
            self._sslwrap_args[4] = ca_certs

        def load_cert_chain(self, certfile, keyfile):
            self._sslwrap_args[0] = keyfile
            self._sslwrap_args[1] = certfile

        def set_ciphers(self, ciphers):
            self._sslwrap_args[5] = ciphers


if hasattr(ssl, 'MemoryBIO'):
    # Python 3.5+
    MemoryBIO = ssl.MemoryBIO

else:
    # Python 2.7, Python 3.3/3.4
    MemoryBIO = _sslcompat.MemoryBIO


if hasattr(ssl, 'SSLObject'):
    # Python 3.5+
    SSLObject = ssl.SSLObject

else:

    # Python 2.7, 3.3 and 3.4
    # SSLObject was copied and adapted from Python 3.5

    class SSLObject(object):
        """An :class:`ssl.SSLObject` implementation for Python 2.7, 3.3 and 3.4."""

        def __init__(self, sslobj, context, server_side, server_hostname):
            self._sslobj = sslobj
            self._context = context
            self._server_side = server_side
            self._server_hostname = server_hostname

        @property
        def context(self):
            return self._context

        @context.setter
        def context(self, ctx):
            if not hasattr(self._sslobj, 'context'):
                raise NotImplementedError('operation not supported by the _ssl module')
            self._sslobj.context = ctx
            self._context = ctx

        @property
        def server_side(self):
            return self._server_side

        @property
        def server_hostname(self):
            return self._server_hostname

        def read(self, len=1024, buffer=None):
            if buffer is not None:
                v = self._sslobj.read(len, buffer)
            else:
                v = self._sslobj.read(len)
            return v

        def write(self, data):
            return self._sslobj.write(data)

        def getpeercert(self, binary_form=False):
            return self._sslobj.peer_certificate(binary_form)

        def selected_npn_protocol(self):
            if hasattr(self._sslobj, 'selected_npn_protocol'):
                return self._sslobj.selected_npn_protocol()

        def selected_alpn_protocol(self):
            if hasattr(self._sslobj, 'selected_alpn_protocol'):
                return self._sslobj.selected_alpn_protocol()

        def cipher(self):
            return self._sslobj.cipher()

        def compression(self):
            if hasattr(self._sslobj, 'compression'):
                return self._sslobj.compression()

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
            if cb_type not in getattr(ssl, 'CHANNEL_BINDING_TYPES', []):
                raise ValueError('Unsupported channel binding type')
            if cb_type != 'tls-unique':
                raise NotImplementedError('{0} channel binding not implemented'.format(cb_type))
            return self._sslobj.tls_unique_cb()

        def version(self):
            if hasattr(self._sslobj, 'version'):
                return self._sslobj.version()


def create_default_context(purpose=None, **kwargs):
    """Create a new SSL context in the most secure way available on the current
    Python version. See :func:`ssl.create_default_context`."""
    if hasattr(ssl, 'create_default_context'):
        # Python 2.7.9+, Python 3.4+: take a server_side boolean or None, in
        # addition to the ssl.Purpose.XX values. This allows a user to write
        # code that works on all supported Python versions.
        if purpose is None or purpose is False:
            purpose = ssl.Purpose.SERVER_AUTH
        elif purpose is True:
            purpose = ssl.Purpose.CLIENT_AUTH
        return ssl.create_default_context(purpose, **kwargs)
    # Python 2.7.8, Python 3.3
    context = SSLContext(ssl.PROTOCOL_SSLv23)
    if kwargs.get('cafile'):
        context.load_verify_locations(kwargs['cafile'])
    return context


def get_dummy_socket():
    # Return a dummy socket that can be wrapped by _ssl, before we replace the
    # socket BIO with our backport of the memory BIO.
    sock = socket.socket()
    if six.PY2:
        sock = sock._sock
    sock.setblocking(False)
    return sock

_sock = None


def wrap_bio(ctx, incoming, outgoing, server_side=False, server_hostname=None):
    # Create a new SSL protocol instance from a context and a BIO pair.
    if hasattr(ctx, 'wrap_bio'):
        # Python 3.5+
        return ctx.wrap_bio(incoming, outgoing, server_side, server_hostname)
    # Allocate a single global dummy socket to wrap on Python < 3.5
    global _sock
    if _sock is None:
        _sock = get_dummy_socket()
    if hasattr(ctx, '_wrap_socket'):
        # Python 2.7.9+, Python 3.3+
        sslobj = ctx._wrap_socket(_sock, server_side, server_hostname)
    else:
        # Python 2.7.x, x <= 8
        sslobj = _ssl.sslwrap(_sock, server_side, *ctx._sslwrap_args)
    _sslcompat.replace_bio(sslobj, incoming, outgoing)
    pyobj = SSLObject(sslobj, ctx, server_side, server_hostname)
    return pyobj


def get_reason(exc):
    # Return the reason code from an SSLError exception.
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
    return _sslcompat.errorcode.get(code, message[p0:p1])
