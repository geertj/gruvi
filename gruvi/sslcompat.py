#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys

if sys.version_info[0] == 3:
    raise ImportError('Only import this module in Python 2.6 or 2.7.')

import _ssl
import ssl
try:
    from . import _sslcompat
except ImportError:
    # Only allow _sslcompat=None on Windows
    if not sys.platform.startswith('win'):
        raise
    _sslcompat = None


__all__ = []

if _sslcompat:
    # Export constants from _sslcompat
    for key in dir(_sslcompat):
        if key[:4].isupper():  # also export FOO_BARv1
            value = getattr(_sslcompat, key)
            globals()[key] = value

    errorcode = _sslcompat.errorcode

else:
    # These should not change, but hope for the best anyway.
    # Only errorcode is really used.
    OP_ALL = 0x800003f7
    OP_NO_SSLv2 = 0x1000000
    errorcode = {207: 'PROTOCOL_IS_SHUTDOWN'}


if hasattr(ssl, '_DEFAULT_CIPHERS'):
    DEFAULT_CIPHERS = ssl._DEFAULT_CIPHERS
else:
    DEFAULT_CIPHERS = 'DEFAULT:!aNULL:!eNULL:!LOW:!EXPORT:!SSLv2'


class SSLContext(object):
    """Compatiblity SSLContext object for Python 2.6 and 2.7.

    This isn't a real SSLContext so it doesn't do things like session
    caching. The purpose is to store arguments to :func:`ssl.wrap_socket` in a
    way that is compatible with Py3k.
    """

    def __init__(self, protocol):
        """
        The *protocol* parameter can be used to set the SSL protocol version.
        The default is to use SSLv3 or higher. This is achieved by setting
        protocol to ``PROTOCOL_SSLv23`` and :attr:`options` to ``OP_NO_SSLv2``.
        Note that ``PROTOCOL_SSLv23`` is a bit of a misnomer as it includes any
        supported TLS version as well.
        """
        # [server_side, keyfile, certfile, cert_reqs, ssl_version, ca_certs]
        self._ssl_args = [False, None, None, ssl.CERT_NONE, protocol, None]
        # Implement the same defaults as the Python ssl module
        self._ciphers = DEFAULT_CIPHERS
        self._options = OP_ALL & OP_NO_SSLv2
        self._dh_params = None

    def _wrap_socket(self, sock, server_side=False, server_hostname=None):
        # We need to do some magic to support anonymous DH authentication. Anon
        # DH doesn't need a certfile and a keyfile, but the Python 2.x
        # _ssl.sslwrap raises an exception if these are absent for server side
        # sockets. So the workaround is to create the socket as a client-side
        # socket and then flip it afterwards if needed.
        # Of course this only works if we have the _sslcompat module.
        if not _sslcompat:
            if server_hostname:
                raise RuntimeError('server_hostname: _sslcompat not available')
            return _ssl.sslwrap(sock, server_side, *self._ssl_args[1:])
        sslobj = _ssl.sslwrap(sock, *self._ssl_args)
        if self._dh_params:
            _sslcompat.load_dh_params(sslobj, self._dh_params)
        if server_side:
            _sslcompat.set_accept_state(sslobj)
        if self._ciphers:
            _sslcompat.set_ciphers(sslobj, self._ciphers)
        _sslcompat.set_options(sslobj, self._options)
        if server_hostname:
            _sslcompat.set_tlsext_host_name(server_hostname)
        return sslobj

    @property
    def protocol(self):
        return self._ssl_args[4]

    @property
    def verify_mode(self):
        return self._ssl_args[3]

    @verify_mode.setter
    def verify_mode(self, cert_reqs):
        self._ssl_args[3] = cert_reqs

    @property
    def options(self):
        return self._options

    @options.setter
    def options(self, options):
        if _sslcompat is None:
            raise RuntimeError('_sslcompat not available')
        self._options = options

    def load_verify_locations(self, ca_certs):
        self._ssl_args[5] = ca_certs

    def load_cert_chain(self, certfile, keyfile):
        self._ssl_args[1] = certfile
        self._ssl_args[2] = keyfile

    def set_ciphers(self, ciphers):
        if _sslcompat is None:
            raise RuntimeError('_sslcompat not availble')
        self._ciphers = ciphers

    def load_dh_params(self, dh_params):
        if _sslcompat is None:
            raise RuntimeError('_sslcompat not availble')
        self._dh_params = dh_params


def compression(sslobj):
    """Return the current compression method for *sslobj*."""
    if hasattr(sslobj, '_sslobj'):
        sslobj = sslobj._sslobj
    if _sslcompat is not None:
        return _sslcompat.compression(sslobj)


def tls_unique_cb(sslobj):
    """Get the "tls-unique" channel bindings for *sslobj."""
    if hasattr(sslobj, '_sslobj'):
        sslobj = sslobj._sslobj
    if _sslcompat is not None:
        return _sslcompat.tls_unique_cb(sslobj)
