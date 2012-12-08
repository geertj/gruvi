#
# This file is part of gruvi. Gruvi is free software available under the terms
# of the MIT license. See the file "LICENSE" that was provided together with
# this source file for the licensing terms.
#
# Copyright (c) 2012 the gruvi authors. See the file "AUTHORS" for a complete
# list.

from __future__ import absolute_import, print_function

import pyuv
import gruvi
import errno
import _socket
import _ssl


def ssl_retry(sslsock, method, args=()):
    start_time = sslsock.hub.loop.now()
    timeout = sslsock.gettimeout()
    while True:
        try:
            return method(*args)
        except _ssl.SSLError as e:
            if e.errno == _ssl.SSL_ERROR_WANT_READ:
                events = pyuv.UV_READABLE
            elif e.errno == _ssl.SSL_ERROR_WANT_WRITE:
                events = pyuv.UV_WRITABLE
            else:
                raise
        if timeout is not None:
            elapsed = sslsock.hub.loop.now() - start_time
            if elapsed > sslsock.timeout:
                raise _socket.timeout()
            secs = timeout - elapsed
            sslsock.hub.wait(sock.timer, secs, 0)
        sslsock.hub.wait(sslsock.poll, events)
        sslsock.hub.switch()


class SSLSocket(gruvi.Socket):

    def __init__(self, hub, sock, keyfile=None, certfile=None,
                 server_side=False, cert_reqs=_ssl.CERT_NONE,
                 ssl_version=_ssl.PROTOCOL_SSLv23, ca_certs=None,
                 do_handshake_on_connect=True, ciphers=None):
        super(SSLSocket, self).__init__(hub, _sock=sock._sock)
        self.hub = hub
        self.keyfile = keyfile
        self.certfile = certfile
        self.server_side = server_side
        self.cert_reqs = cert_reqs
        self.ssl_version = ssl_version
        self.ca_certs = ca_certs
        self.do_handshake_on_connect = do_handshake_on_connect
        self._wrapped = sock
        self._ssl_enabled = False
        try:
            name = sock.getpeername()
        except _socket.error as e:
            if e.errno != errno.ENOTCONN:
                raise
            self._sslobj = None
        else:
            self._sslobj = _ssl.sslwrap(self._sock, server_side, keyfile,
                                        certfile, cert_reqs, ssl_version,
                                        ca_certs, ciphers)
            if do_handshake_on_connect:
                self.do_handshake()

    def do_handshake(self):
        if self._sslobj is None:
            raise RuntimeError('not connected')
        ssl_retry(self, self._sslobj.do_handshake)

    def unwrap(self):
        if self._sslobj is None:
            raise RuntimeError('not connected')
        ssl_retry(self, self._sslobj.shutdown)
        return self._wrapped

    def getpeercert(self, binary_form=False):
        if self._sslobj is None:
            raise RuntimeError('not connected')
        return self._sslobj.getpeercert(binary_form)

    def cipher(self):
        if self._sslobj is None:
            raise RuntimeError('not connected')
        return self._sslobj.cipher()

    def accept(self):
        sock, addr = super(SSLSocket, self).accept()
        cls = type(self)
        sslsock = cls(self.hub, sock, keyfile=self.keyfile,
                      certfile=self.certfile, server_side=True,
                      cert_reqs=self.cert_reqs, ssl_version=self.ssl_version,
                      ca_certs=self.ca_certs,
                      do_handshake_on_connect=self.do_handshake_on_connect,
                      ciphers=ciphers)
        return sslsock, addr

    def connect(self, address):
        super(SSLSocket, self).connect(address)
        self._sslobj = _ssl.sslwrap(self._sock, server_side, keyfile,
                                    certfile, cert_reqs, ssl_version,
                                    ca_certs, ciphers)
        if self.do_handshake_on_connect:
            self.do_handshake()

    def recv(self, nbytes=1024, flags=0):
        if self._sslobj is None:
            raise RuntimeError('not connected')
        if flags != 0:
            raise ValueError('cannot specify flags when ssl is active')
        try:
            return ssl_retry(self, self._sslobj.read, (nbytes,))
        except _ssl.SSLError as e:
            if e.errno == _ssl.SSL_ERROR_EOF:
                return ''
            raise

    def recvfrom(self, nbytes=1024, flags=0):
        raise NotImplementedError('not available on SSLSocket')

    def recv_into(self, buf, nbytes=None, flags=0):
        raise NotImplementedError('not available on SSLSocket')

    def recvfrom_into(self, buf, nbytes=None, flags=0):
        raise NotImplementedError('not available on SSLSocket')

    def send(self, buf, flags=0):
        if self._sslobj is None:
            raise RuntimeError('not connected')
        if flags != 0:
            raise ValueError('cannot specify flags when ssl is active')
        return ssl_retry(self, self._sslobj.write, (buf,))

    def sendto(self, data, flags_or_addr, addr=None):
        raise NotImplementedError('not available on SSLSocket')

    def close(self):
        super(SSLSocket, self).close()
        self._sslobj = None

    def shutdown(self, how):
        super(SSLSocket, self).shutdown(how)
        self._sslobj = None
