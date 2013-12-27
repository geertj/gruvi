#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.
"""
This module contains a HTTP/1.1 client and server.

The client and server are relatively complete implementations of the HTTP/1.1
protocol. The server also has best-efforts support for 1.0 clients. Some of the
supported features are: keepalive, pipelining, chunked transfers and trailers.

Some general notes:

* Keepalive is the default so be sure to close connections when no longer
  needed.
* Any headers that are passed in by application code must not be "Hop by hop"
  headers. These headers may only be used by HTTP implementations themselves,
  such as the client and server in this module.
* Strings passed into the API, other than those that end up in the HTTP body,
  must be of a text type (str or unicode in Python 2.x, str in Python 3.x).
  These strings must only contain code points that are in ISO-8859-1. This is
  the default encoding for HTTP as per RFC2606.
* Strings passed into the API that will end up in the HTTP body can be either
  of a binary or a text type. If they are of a text type, then they must only
  contain code points that are in ISO-8859-1.
* To include a text in a body that contains code points outside ISO-8859-1,
  encode it yourself in a suitable encoding (UTF-8 is a good choice), set the
  "charset" parameter to the "Content-Type" header to the encoding you used,
  and pass the body as a binary type.
"""

from __future__ import absolute_import, print_function

import os.path
import collections

from . import hub, protocols, error, reader, http_ffi, logging, compat
from .hub import switchpoint
from .util import objref, docfrom, getsockname
from ._version import __version__

try:
    from urllib.parse import urlsplit
except ImportError:
    from urlparse import urlsplit

__all__ = ['HttpError', 'HttpClient', 'HttpServer', 'HttpResponse', 'geturlinfo']


# The "Hop by Hop" headers as defined in RFC 2616. These may not be set by the
# WSGI application.
hop_by_hop = frozenset(('Connection', 'Keep-Alive', 'Proxy-Authenticate',
                        'Proxy-Authorization', 'TE', 'Trailers',
                        'Transfer-Encoding', 'Upgrade'))


def geturlinfo(url):
    """Return connection information for a url.
    
    The *url* parameter must be a a string.
    
    The return value is a (host, port, ssl, path) tuple.
    """
    parsed = urlsplit(url)
    try:
        hort, port = parsed.netloc.split(':')
        port = int(port)
    except ValueError:
        host = parsed.netloc
        port = 443 if parsed.scheme == 'https' else 80
    ssl = parsed.scheme == 'https'
    path = (parsed.path + parsed.query) or '/'
    return (host, port, ssl, path)


def _s2b(s):
    """Convert a string *s* to bytes in the ISO-8859-1 encoding.
    
    ISO-8859-1 is the default encoding used in HTTP.
    """
    if type(s) is not bytes:
        s = s.encode('iso-8859-1')
    return s

def _ba2str(ba):
    """Convert a byte-array to a "str" type."""
    if compat.PY3:
        return ba.decode('iso-8859-1')
    else:
        return bytes(ba)

def _cp2str(cd):
    """Convert a cffi cdata('char *') to a str."""
    s = http_ffi.ffi.string(cd)
    if compat.PY3:
        s = s.decode('iso-8859-1')
    return s


def get_header(headers, name, default=None):
    """Return a header value from a header list."""
    name = name.lower()
    for header in headers:
        if header[0].lower() == name:
            return header[1]
    return default


def create_chunk(buf):
    """Create a chunk for the HTTP "chunked" transfer encoding."""
    chunk = bytearray()
    chunk.extend(_s2b('{0:X}\r\n'.format(len(buf))))
    chunk.extend(_s2b(buf))
    chunk.extend(b'\r\n')
    return chunk


def last_chunk(trailers=[]):
    """Return the last chunk."""
    chunk = bytearray()
    chunk.extend(b'0\r\n')
    for name,value in trailers:
        chunk.extend(_s2b('{0}: {1}\r\n'.format(name, value)))
    chunk.extend(b'\r\n')
    return chunk


def create_request(method, url, headers):
    """Create a HTTP request message (no body). Always HTTP/1.1."""
    message = bytearray()
    message.extend(_s2b('{0} {1} HTTP/1.1\r\n'.format(method, url)))
    for name,value in headers:
        message.extend(_s2b('{0}: {1}\r\n'.format(name, value)))
    message.extend(b'\r\n')
    return message


def create_response(version, status, headers):
    """Create a HTTP response message (no body)."""
    message = bytearray()
    message.extend(_s2b('HTTP/{0[0]}.{0[1]} {1}\r\n'.format(version, status)))
    for name,value in headers:
        message.extend(_s2b('{0}: {1}\r\n'.format(name, value)))
    message.extend(b'\r\n')
    return message


class HttpError(error.Error):
    """Exception that is raised in case of HTTP protocol errors."""


class HttpMessage(object):
    """A HTTP message (request or response). Used by the parser."""

    def __init__(self):
        self.message_type = None
        self.version = None
        self.status_code = None
        self.method = None
        self.url = None
        self.is_upgrade = None
        self.should_keep_alive = None
        self.parsed_url = None
        self.headers = []
        self.trailers = []
        self.buffers = reader.BufferList()
        self.body = reader.Reader(self.buffers)

    def __len__(self):
        # Use a fixed header size of 400. This is for flow control purposes
        # only, this does not need to be exact.
        return 400 + self.buffers.size

    def get_wsgi_environ(self):
        """Return a WSGI environment dictionary for the current message."""
        if self.message_type != HttpParser.HTTP_REQUEST:
            raise ValueError('expecting an HTTP request')
        env = {}
        env['REQUEST_METHOD'] = self.method
        env['SERVER_PROTOCOL'] = 'HTTP/{0}.{1}'.format(*self.version)
        env['REQUEST_URI'] = self.url
        env['SCRIPT_NAME'] = ''
        env['PATH_INFO'] = self.parsed_url[3]
        env['QUERY_STRING'] = self.parsed_url[4]
        for field,value in self.headers:
            if field.title() == 'Content-Length':
                env['CONTENT_LENGTH'] = value
            elif field.title() == 'Content-Type':
                env['CONTENT_TYPE'] = value
            else:
                env['HTTP_{0}'.format(field.upper().replace('-', '_'))] = value
        env['wsgi.input'] = self.body
        return env


class HttpResponse(object):
    """An HTTP response as returned by :meth:`HttpClient.getresponse`."""

    def __init__(self, message):
        self._message = message

    @property
    def version(self):
        """The HTTP version as a (major, minor) tuple."""
        return self._message.version

    @property
    def status(self):
        """The HTTP status code, as an integer."""
        return self._message.status_code

    @property
    def headers(self):
        """The response headers, as a list of (name, value) pairs."""
        return self._message.headers

    @property
    def trailers(self):
        """The response trailers, as a list of (name, value) pairs.

        The trailers will only be available after the entire response has been
        read. Most servers do not generate trailers.
        """
        return self._message.trailers

    def get_header(self, name, default=None):
        """Return one HTTP header *name*. If no such header exists, *default*
        is returned."""
        return get_header(self._message.headers, name, default)

    @switchpoint
    @docfrom(reader.Reader.read)
    def read(self, size=None):
        return self._message.body.read(size)

    @switchpoint
    @docfrom(reader.Reader.readline)
    def readline(self, limit=-1):
        return self._message.body.readline(limit)

    @switchpoint
    @docfrom(reader.Reader.readlines)
    def readlines(self, hint=-1):
        return self._message.body.readlines(hint)

    @property
    def __iter__(self):
        return self._mesasge.body.__iter__


class HttpParser(protocols.Parser):
    """A HTTP parser.

    This is a class based interface on top of the node.js http-parser (accessed
    via CFFI).
    """

    s_header_field, s_header_value = range(2)

    HTTP_REQUEST = http_ffi.lib.HTTP_REQUEST
    HTTP_RESPONSE = http_ffi.lib.HTTP_RESPONSE
    HTTP_BOTH = http_ffi.lib.HTTP_BOTH

    def __init__(self, kind=None):
        super(HttpParser, self).__init__()
        if kind is None:
            kind = self.HTTP_BOTH
        self._kind = kind
        self._parser = http_ffi.ffi.new('http_parser *')
        http_ffi.lib.http_parser_init(self._parser, self._kind)
        self._setup_callbacks()
        self._requests = collections.deque()

    @property
    def requests(self):
        return self._requests

    def push_request(self, method):
        """Inform the parser that a request for *method* has been made.

        This information is required by the parser because needs to know if a
        response was caused by a HEAD request or not. A HEAD response is
        special because it never has a response entity, even if it includes
        a Content-Length that suggests otherwise.
        """
        if self._kind == self.HTTP_REQUEST:
            raise RuntimeError('push_request() is for response parsers only')
        self._requests.append(method)

    def feed(self, s):
        nbytes = http_ffi.lib.http_parser_execute(self._parser, self._settings, s, len(s))
        if nbytes != len(s):
            self._error = http_ffi.lib.http_errno(self._parser)
            self._error_message = _cp2str(http_ffi.lib.http_errno_name(errno))
        return nbytes

    def _setup_callbacks(self):
        settings = http_ffi.ffi.new('http_parser_settings *')
        callback_refs = {}  # prevent garbage collection of cffi callbacks
        names = [ name for name in dir(self) if name.startswith('_on_') ]
        for name in names:
            cbtype = 'http_cb' if 'complete' in name or 'begin' in name \
                            else 'http_data_cb'
            cb = http_ffi.ffi.callback(cbtype, getattr(self, name))
            callback_refs[name] = cb
            setattr(settings, name[1:], cb)
        self._settings = settings
        self._callback_refs = callback_refs

    def _reinit(self):
        self._url_data = bytearray()
        self._header_state = self.s_header_field
        self._header_name = None
        self._header_data = bytearray()
        self._message = HttpMessage()
        self._headers_complete = False

    def _on_message_begin(self, parser):
        self._reinit()
        return 0

    def _on_url(self, parser, at, length):
        buf = http_ffi.ffi.buffer(at, length)
        self._url_data.extend(buf)
        return 0

    def _on_header_field(self, parser, at, length):
        buf = http_ffi.ffi.buffer(at, length)
        if self._header_state == self.s_header_field:
            self._header_data.extend(buf)
        else:
            header_value = _ba2str(self._header_data)
            dest = self._message.trailers if self._headers_complete \
                        else self._message.headers
            dest.append((self._header_name, header_value))
            self._header_data[:] = buf
            self._header_state = self.s_header_field
        return 0

    def _on_header_value(self, parser, at, length):
        buf = http_ffi.ffi.buffer(at, length)
        if self._header_state == self.s_header_value:
            self._header_data.extend(buf)
        else:
            self._header_name = _ba2str(self._header_data)
            self._header_data[:] = buf
            self._header_state = self.s_header_value
        return 0

    def _parse_url(self, url):
        msg = self._message
        result = http_ffi.ffi.new('struct http_parser_url *')
        is_connect = msg.method == 'CONNECT'
        error = http_ffi.lib.http_parser_parse_url(bytes(url), len(url),
                                                   is_connect, result)
        if error:
            raise ValueError('url parse error')
        parsed_url = []
        m = http_ffi.lib
        for field in (m.UF_SCHEMA, m.UF_HOST, m.UF_PORT, m.UF_PATH, m.UF_QUERY,
                      m.UF_FRAGMENT, m.UF_USERINFO):
            if result.field_set & (1 << field):
                data = result.field_data[field]
                component = _ba2str(url[data.off:data.off+data.len])
            else:
                component = ''
            parsed_url.append(component)
        return parsed_url

    def _on_headers_complete(self, parser):
        if self._header_state == self.s_header_value:
            header_value = _ba2str(self._header_data)
            self._message.headers.append((self._header_name, header_value))
            self._header_state = self.s_header_field
            del self._header_data[:]
        msg = self._message
        msg.message_type = http_ffi.lib.http_message_type(parser)
        msg.version = (parser.http_major, parser.http_minor)
        if msg.message_type == self.HTTP_REQUEST:
            msg.method = _cp2str(http_ffi.lib.http_method_str(parser.method))
            msg.url = _ba2str(self._url_data)
            try:
                msg.parsed_url = self._parse_url(self._url_data)
            except ValueError:
                return 2
            msg.is_upgrade = http_ffi.lib.http_is_upgrade(parser)
        else:
            msg.status_code = parser.status_code
        msg.should_keep_alive = http_ffi.lib.http_should_keep_alive(parser)
        # The message is made available immediately after the headers are
        # complete. We keep a reference to it, so that we can append the entity
        # if and when we receive it.
        self._messages.append(msg)
        self._headers_complete = True
        request_method = self._requests and self._requests.popleft()
        return 1 if request_method == 'HEAD' else 0

    def _on_body(self, parser, at, length):
        buf = http_ffi.ffi.buffer(at, length)[:]  # -> bytes
        self._message.buffers.feed(buf)
        return 0

    def _on_message_complete(self, parser):
        if self._header_state == self.s_header_value:
            # last trailer in a chunked messages
            header_value = _ba2str(self._header_data)
            dest = self._message.trailers if self._headers_complete \
                        else self._message.headers
            dest.append((self._header_name, header_value))
        self._message.buffers.feed(b'')
        return 0


class ErrorStream(object):
    """Passed to the WSGI application as environ['wsgi.errors'].

    Forwards messages to the Python logging facility.
    """

    def __init__(self):
        self._log = logging.get_logger(objref(self))

    def flush(self):
        pass
    
    def write(self, data):
        self._log.error(data)

    def writelines(self, seq):
        for line in seq:
            self.write(line)


class HttpClient(protocols.RequestResponseProtocol):
    """An HTTP/1.1 client."""

    _exception = HttpError
    user_agent = 'Gruvi/{0}'.format(__version__)

    def __init__(self, timeout=None):
        """The optional *timeout* argument can be used to specify a timeout for
        the various network operations used within the client."""
        def parser_factory():
            return HttpParser(HttpParser.HTTP_RESPONSE)
        super(HttpClient, self).__init__(parser_factory, timeout=timeout)
        self._default_host = None

    transport = protocols.Protocol.transport  # Have Sphinx document it

    @switchpoint
    @docfrom(protocols.Protocol._connect)
    def connect(self, address, ssl=False, local_address=None,
                **transport_args):
        self._connect(address, ssl, local_address, **transport_args)
        if isinstance(address, tuple):
            self._default_host = address[0]

    def _init_transport(self, transport):
        super(HttpClient, self)._init_transport(transport)
        # HTTP is a non-interactive protocol, so set TCP_NODELAY by default
        # The client makes sure to coalesce small writes itself.
        if hasattr(transport, 'nodelay'):
            transport.nodelay(True)

    def _dispatch_fast_path(self, transport, message):
        # When the user reads data from the HTTP body, or when the parser feeds
        # body data into it, the total number of bytes buffered in the queue
        # changes, even though no element was added or removed. Whenever this
        # happens, use the semi-private _adjust_size() method to adjust the
        # queue size. This ensurs that transport._queue.size() is always an
        # accurate reflection of how many bytes are buffered, and we can use it
        # for flow control.
        def on_size_change(oldsize, newsize):
            transport._queue._adjust_size(newsize-oldsize)
        message.buffers.size_changed.connect(on_size_change)
        # Do not go through the dispatcher in the client. Put the message
        # straight into the queue, and complete the fast path.
        transport._queue.put(message)
        return True

    @switchpoint
    def request(self, method, url, headers=None, body=None):
        """Make a new HTTP request.

        The *method* argument is the HTTP method to be used. It must be
        specified  as a string, for example ``'GET'`` or ``'POST'``. The *url*
        argument must be a string containing the URL.

        The optional *headers* argument specifies extra HTTP headers to use in
        the request. It must be a list of (name, value) tuples, with name and
        value a string.

        The optional *body* argument may be used to specify a body to include
        in the request. It must be a ``bytes`` or ``str`` instance, a file-like
        object, or an iterable producing ``bytes`` or ``str`` instances. See
        the notes at the top about the use of strings in HTTP bodies.

        This method sends the request and waits for it to be complete sent out.
        It does now however wait for the response. The response can be obtained
        using :meth:`getresponse`.
        
        You may make multiple requests before reading a response. This is
        called pipelining. According to the HTTP RFC, you should not use the
        POST method when doing this. This restriction is not enforced by this
        method.
        """
        if self._transport is None or self._transport.closed:
            raise RuntimeError('not connected')
        headers = [] if headers is None else headers[:]
        for name,value in headers:
            if name in hop_by_hop:
                raise ValueError('header {0} is hop-by-hop'.format(name))
        agent = get_header(headers, 'User-Agent')
        if agent is None:
            headers.append(('User-Agent', self.user_agent))
        host = get_header(headers, 'Host')
        if host is None and self._default_host:
            headers.append(('Host', self._default_host))
        if body is None:
            body = b''
        if isinstance(body, (compat.binary_type, compat.text_type)):
            body = _s2b(body)
            headers.append(('Content-Length', str(len(body))))
        elif hasattr(body, 'read') or hasattr(body, '__iter__'):
            headers.append(('Transfer-Encoding', 'chunked'))
        else:
            raise TypeError('body: expecting a bytes or str instance, ' \
                            'a file-like object, or an iterable')
        self._transport._parser.push_request(method)
        header = create_request(method, url, headers)
        self._transport.write(header)
        if isinstance(body, bytes):
            self._write(self._transport, body)
        elif hasattr(body, 'read'):
            while True:
                chunk = body.read(4096)
                if not chunk:
                    break
                self._write(self._transport, create_chunk(chunk))
            self._write(self._transport, last_chunk())
        elif hasattr(body, '__iter__'):
            for chunk in body:
                self._write(self._transport, create_chunk(chunk))
            self._write(self._transport, last_chunk())
        self._flush(self._transport)

    @switchpoint
    def getresponse(self):
        """Get a new response from the connection.

        This method will wait until the reponse header is fully received. It
        will then parse the response header, store the result in a
        :class:`HttpResponse` instance, and return that. The rest of the body
        may be read through the response object.

        When using HTTP pipelining, this method will return the fist response
        header that is received, which will correspond to the oldest request
        that is still pending.
        """
        if not self._transport._parser.requests and not self._transport._queue:
            raise RuntimeError('there are no outstanding requests')
        message = self._transport._queue.get()
        response = HttpResponse(message)
        return response


class HttpServer(protocols.RequestResponseProtocol):
    """An HTTP 1/1. server."""

    _exception = HttpError
    server_id = 'gruvi.http/{0}'.format(__version__)

    def __init__(self, wsgi_handler, server_name=None, timeout=None):
        """The constructor takes the following arugments.  The *wsgi_handler*
        argument must be a WSGI callable. See `PEP 333
        <http://www.python.org/dev/peps/pep-0333/>`_.

        The optional *server_name* argument can be used to specify a server
        name. This might be needed by the WSGI application to construct
        absolute URLs. If not provided, then the host portion of the address
        passed to :meth:`listen` will be used.

        The optional *timeout* argument can be used to specify a timeout for
        the various network operations used within the server.
        """
        def parser_factory():
            return HttpParser(HttpParser.HTTP_REQUEST)
        super(HttpServer, self).__init__(parser_factory, timeout)
        self._wsgi_handler = wsgi_handler
        self._server_name = server_name

    transport = protocols.Protocol.transport  # Have Sphinx document it

    @property
    def clients(self):
        """A set containing the transports of the currently connected
        clients."""
        return self._clients

    @switchpoint
    @docfrom(protocols.Protocol._listen)
    def listen(self, address, ssl=False, **transport_args):
        self._listen(address, ssl, **transport_args)

    def _init_transport(self, transport):
        super(HttpServer, self)._init_transport(transport)
        if hasattr(transport, 'nodelay'):
            transport.nodelay(True)
        self._reinit_request(transport)

    def _reinit_request(self, transport):
        transport._version = None
        transport._status = None
        transport._headers = []
        transport._trailers = []
        transport._headers_sent = False
        transport._chunked = None
        transport._keepalive = None

    def _dispatch_fast_path(self, transport, message):
        def on_size_change(oldsize, newsize):
            transport._queue._adjust_size(newsize-oldsize)
        message.buffers.size_changed.connect(on_size_change)
        return False

    def _close_transport(self, transport, error=None):
        if not transport.closed and not transport._headers_sent and error:
            transport._status = '500 Internal Server Error'
            transport._headers = [('Content-Type', 'text/plain')]
            transport._chunked = False
            transport._keepalive = False
            self._write(transport, 'Internal Server Error ({0})'
                                        .format(error.args[0]))
        super(HttpServer, self)._close_transport(transport)

    def _get_environ(self, transport, message):
        env = message.get_wsgi_environ()
        addr = getsockname(self.transport)
        if isinstance(addr, (compat.binary_type, compat.text_type)):
            addr = (addr, None)
        env['SERVER_NAME'] = self._server_name or addr[0]
        env['SERVER_PORT'] = addr[1]
        env['wsgi.version'] = (1, 0)
        errors = env['wsgi.errors'] = ErrorStream()
        transport._log.debug('logging to {}', objref(errors))
        env['wsgi.multithread'] = True
        env['wsgi.multiprocess'] = True
        env['wsgi.run_once'] = False
        return env

    def _send_headers(self, transport):
        clen = get_header(transport._headers, 'Content-Length')
        transport._chunked = clen is None and transport._version == (1, 1)
        if transport._chunked:
            transport._headers.append(('Transfer-Encoding', 'chunked'))
        if not clen and transport._version == (1, 0):
            transport._keepalive = False
        if transport._version == (1, 1) and not transport._keepalive:
            transport._headers.append(('Connection', 'close'))
        elif transport._version == (1, 0) and transport._keepalive:
            transport._headers.append(('Connection', 'keep-alive'))
        server = get_header(transport._headers, 'Server')
        if server is None:
            transport._headers.append(('Server', self.server_id))
        header = create_response(transport._version, transport._status,
                                 transport._headers)
        transport.write(header)
        transport._headers_sent = True

    @switchpoint
    def _write(self, transport, data, last=False):
        if isinstance(data, compat.text_type):
            data = data.encode('iso-8859-1')
        elif not isinstance(data, compat.binary_type):
            raise TypeError('data: expecting bytes or str instance')
        if not data and not last:
            return
        if transport._error:
            raise transport._error
        if not transport._headers_sent:
            self._send_headers(transport)
        if transport._chunked:
            if data:
                data = create_chunk(data)
            if last:
                data += last_chunk(transport._trailers)
        super(HttpServer, self)._write(transport, data)

    def _start_response(self, transport, status, headers, exc_info=None):
        if exc_info:
            try:
                if transport._headers_sent:
                    compat.reraise(*exc_info)
            finally:
                exc_info = None
        elif transport._status is not None:
            raise RuntimeError('response already started')
        for name,value in headers:
            if name in hop_by_hop:
                raise ValueError('header {0} is hop-by-hop'.format(name))
        transport._status = status
        transport._headers = headers
        def write(data):
            return self._write(transport, data, last=False)
        return write

    def _dispatch_message(self, transport, message):
        transport._log.info('request: {} {}', message.method, message.url)
        transport._version = message.version
        transport._keepalive = message.should_keep_alive
        environ = self._get_environ(transport, message)
        def start_response(status, headers, exc_info=None):
            return self._start_response(transport, status, headers, exc_info)
        result = self._wsgi_handler(environ, start_response)
        try:
            if not transport._status:
                raise RuntimeError('start_response() not called')
            for chunk in result:
                if transport.closed:
                    break
                if chunk:
                    self._write(transport, chunk)
            self._write(transport, b'', last=True)
            self._flush(transport)
        finally:
            if hasattr(result, 'close'):
                result.close()
        transport._log.info('response: {}', transport._status)
        if transport._keepalive:
            transport._log.debug('keeping connection alive')
            self._reinit_request(transport)
        else:
            self._close_transport(transport)
