#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
The :mod:`gruvi.http` module implements a HTTP client and server.

The client and server are relatively complete implementations of the HTTP
protocol. Some of the supported features are keepalive, pipelining, chunked
transfers and trailers.

This implementation supports both HTTP/1.0 and HTTP/1.1. The default for the
client is 1.1, and the server will respond with the same version as the client.

Connections are kept alive by default. This means that you need to make sure
you close connections when they are no longer needed, by calling the
appropriate :meth:`~gruvi.Endpoint.close` method.

It is important to clarify how the API exposed by this module uses text and
binary data. Data that is read from or written to the HTTP header, such as the
version string, method, and headers, are text strings (``str`` on Python 3,
``str`` or ``unicode`` on Python 2). However, if the string type is unicode
aware (``str`` on Python 3, ``unicode`` on Python 2), you must make sure that
it only contains code points that are part of ISO-8859-1, which is the default
encoding specified in :rfc:`2606`. Data that is read from or written to HTTP
bodies is always binary. This is done in alignment with the WSGI spec that
requires this.

This module provides a number of APIs. Client-side there is one:

* A :class:`gruvi.Client` based API. You will use :meth:`~HttpClient.connect`
  to connect to a server, and then use :meth:`~HttpClient.request` and
  :meth:`~HttpClient.getresponse` to interact with it.

The following server-side APIs are available:

* A :class:`gruvi.Server` based API. Incoming HTTP messages are passed to a
  message handler that needs to take care of all aspects of HTTP other than
  parsing.
* A WSGI API, as described in :pep:`333`.

The server-side API is selected through the *adapter* argument to
:class:`HttpServer` constructor. The default adapter is :class:`WsgiAdapter`,
which implements the WSGI protocol. To use the raw server interface, pass the
identity function (``lambda x: x``).
"""

from __future__ import absolute_import, print_function

import re
import time
import functools
import six
from collections import namedtuple

from . import logging, compat
from .hub import switchpoint
from .util import delegate_method, docfrom
from .protocols import MessageProtocol, ProtocolError
from .stream import Stream
from .endpoints import Client, Server
from .http_ffi import lib, ffi

from six.moves import http_client

__all__ = ['HttpError', 'ParsedUrl', 'parse_url', 'HttpMessage', 'HttpRequest',
           'HttpProtocol', 'WsgiAdapter', 'HttpClient', 'HttpServer']


#: Constant indicating a HTTP request.
REQUEST = lib.HTTP_REQUEST

#: Constant indicating a HTTP response.
RESPONSE = lib.HTTP_RESPONSE

# Export some definitions from  http.client.
for name in dir(http_client):
    value = getattr(http_client, name)
    if not name.isupper() or not isinstance(value, int):
        continue
    if value in http_client.responses:
        globals()[name] = value

HTTP_PORT = http_client.HTTP_PORT
HTTPS_PORT = http_client.HTTPS_PORT
responses = http_client.responses


# The "Hop by Hop" headers as defined in RFC 2616. These may not be set by the
# HTTP handler.
hop_by_hop = frozenset(('connection', 'keep-alive', 'proxy-authenticate',
                        'proxy-authorization', 'te', 'trailers',
                        'transfer-encoding', 'upgrade'))


# Keep a cache of http-parser's HTTP methods numbers -> method strings
_http_methods = {}

for i in range(100):
    method = ffi.string(lib.http_method_str(i)).decode('ascii')
    if not method.isupper():
        break
    _http_methods[i] = method


class HttpError(ProtocolError):
    """Exception that is raised in case of HTTP protocol errors."""


# Header parsing

# RFC 2626 section 2.2 grammar definitions:
re_ws = re.compile('([ \t]+)')
re_token = re.compile('([!#$%&\'*+\-.0-9A-Z^_`a-z|~]+)')
re_qstring = re.compile(r'"(([\t !\x23-\x5b\x5d-\xff]|\\[\x00-\x7f])*)"')
re_qpair = re.compile(r'\\([\x00-\x7f])')
re_qvalue = re.compile('[qQ]=(1(\.0{0,3})?|0(\.[0-9]{0,3})?)')


def lookahead(buf, pos):
    """Return the next char at the current buffer position."""
    if pos >= len(buf):
        return None
    return buf[pos]

def accept_ws(buf, pos):
    """Skip whitespace at the current buffer position."""
    match = re_ws.match(buf, pos)
    if not match:
        return None, pos
    return buf[match.start(0):match.end(0)], match.end(0)

def accept_lit(char, buf, pos):
    """Accept a literal character at the current buffer position."""
    if pos >= len(buf) or buf[pos] != char:
        return None, pos
    return char, pos+1

def expect_lit(char, buf, pos):
    """Expect a literal character at the current buffer position."""
    if pos >= len(buf) or buf[pos] != char:
        return None, len(buf)
    return char, pos+1

def accept_re(regexp, buf, pos):
    """Accept a regular expression at the current buffer position."""
    match = regexp.match(buf, pos)
    if not match:
        return None, pos
    return buf[match.start(1):match.end(1)], match.end(0)

def expect_re(regexp, buf, pos):
    """Require a regular expression at the current buffer position."""
    match = regexp.match(buf, pos)
    if not match:
        return None, len(buf)
    return buf[match.start(1):match.end(1)], match.end(0)


def parse_content_type(header):
    """Parse the "Content-Type" header."""
    typ = subtyp = None; options = {}
    typ, pos = expect_re(re_token, header, 0)
    _, pos = expect_lit('/', header, pos)
    subtyp, pos = expect_re(re_token, header, pos)
    ctype = header[:pos] if subtyp else ''
    while pos < len(header):
        _, pos = accept_ws(header, pos)
        _, pos = expect_lit(';', header, pos)
        _, pos = accept_ws(header, pos)
        name, pos = expect_re(re_token, header, pos)
        _, pos = expect_lit('=', header, pos)
        char = lookahead(header, pos)
        if char == '"':
            value, pos = expect_re(re_qstring, header, pos)
            value = re_qpair.sub('\\1', value)
        elif char:
            value, pos = expect_re(re_token, header, pos)
        if name and value is not None:
            options[name] = value
    return ctype, options

def parse_te(header):
    """Parse the "TE" header."""
    pos = 0
    names = []
    while pos < len(header):
        name, pos = expect_re(re_token, header, pos)
        _, pos = accept_ws(header, pos)
        _, pos = accept_lit(';', header, pos)
        _, pos = accept_ws(header, pos)
        qvalue, pos = accept_re(re_qvalue, header, pos)
        if name:
            names.append((name, qvalue))
        _, pos = accept_ws(header, pos)
        _, pos = expect_lit(',', header, pos)
        _, pos = accept_ws(header, pos)
    return names

def parse_trailer(header):
    """Parse the "Trailer" header."""
    pos = 0
    names = []
    while pos < len(header):
        name, pos = expect_re(re_token, header, pos)
        if name:
            names.append(name)
        _, pos = accept_ws(header, pos)
        _, pos = expect_lit(',', header, pos)
        _, pos = accept_ws(header, pos)
    return names


weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
rfc1123_fmt = '%a, %d %b %Y %H:%M:%S GMT'

def rfc1123_date(timestamp=None):
    """Create a RFC1123 style Date header for *timestamp*."""
    if timestamp is None:
        timestamp = int(time.time())
    # The time stamp must be GMT, and cannot be localized.
    tm = time.gmtime(timestamp)
    s = rfc1123_fmt.replace('%a', weekdays[tm.tm_wday]) \
                   .replace('%b', months[tm.tm_mon-1])
    return time.strftime(s, tm)


# URL parser (using http-parser). Unlike Python's urlsplit() this doesn't do
# relatively URLs. This is a benefit IMHO, because that allows us to recognize
# absolute URLs with a missing schema ('www.example.com') and not mistaken them
# for the path component of a relative URL. To parse relative URLs you need to
# first turn them into origin-form or absolute-form.

default_ports = {'http': 80, 'https': 443, 'ws': 80, 'wss': 443}
ssl_protocols = frozenset(('https', 'wss'))
url_field_names = ('scheme', 'host', 'path', 'query', 'fragment', 'port', 'userinfo')
url_field_indices = tuple((getattr(lib, 'UF_{}'.format(name.replace('scheme', 'schema')).upper())
                           for name in url_field_names))

class ParsedUrl(namedtuple('_ParsedUrl', url_field_names)):
    """A :func:`~collections.namedtuple` with the following fields:
    ``scheme``, ``host``, ``port``, ``path``, ``query``, ``fragment`` and
    ``userinfo``.

    In addition to the tuple fields the following properties are defined:
    """

    __slots__ = ()

    @classmethod
    def from_parser(cls, parser, url):
        values = []
        for ix in url_field_indices:
            if parser.field_set & (1 << ix):
                fd = parser.field_data[ix]
                values.append(url[fd.off:fd.off+fd.len])
            else:
                values.append('')
        return cls(*values)

    @property
    def addr(self):
        """Address tuple that can be used with :func:`~gruvi.create_connection`."""
        port = self.port
        if port:
            port = int(port)
        else:
            port = default_ports.get(self.scheme or 'http')
        return (self.host, port)

    @property
    def ssl(self):
        """Whether the scheme requires SSL/TLS."""
        return self.scheme in ssl_protocols

    @property
    def target(self):
        """The "target" i.e. local part of the URL, consisting of the path and query."""
        target = self.path or '/'
        if self.query:
            target = '{}?{}'.format(target, self.query)
        return target

ParsedUrl.__new__.__doc__ = ''
ParsedUrl.__new__.__defaults__ = ('',) * len(url_field_names)


def parse_url(url, default_scheme='http', is_connect=False):
    """Parse an URL and return its components.

    The *default_scheme* argument specifies the scheme in case URL is
    an otherwise valid absolute URL but with a missing scheme.

    The *is_connect* argument must be set to ``True`` if the URL was requested
    with the HTTP CONNECT method. These URLs have a different form and need to
    be parsed differently.

    The result is a :class:`ParsedUrl` containing the URL components.
    """
    # If this is not in origin-form, authority-form or asterisk-form and no
    # scheme is present, assume it's in absolute-form with a missing scheme.
    # See RFC7230 section 5.3.
    if url[:1] not in '*/' and not is_connect and '://' not in url:
        url = '{}://{}'.format(default_scheme, url)
    burl = s2b(url)
    parser = ffi.new('struct http_parser_url *')
    lib.http_parser_url_init(parser)
    res = lib.http_parser_parse_url(ffi.from_buffer(burl), len(burl), is_connect, parser)
    if res != 0:
        raise ValueError('invalid URL')
    parsed = ParsedUrl.from_parser(parser, url)
    return parsed


# String conversions. Note that ISO-8859-1 is the default encoding for HTTP
# headers.

def s2b(s):
    """Convert a string *s* to bytes in the ISO-8859-1 encoding."""
    if type(s) is not bytes:
        s = s.encode('iso-8859-1')
    return s

def ba2s(ba):
    """Convert a byte-array to a "str" type."""
    if six.PY3:
        return ba.decode('iso-8859-1')
    else:
        return bytes(ba)

def cd2s(cd):
    """Convert a cffi cdata('char *') to a str."""
    s = ffi.string(cd)
    if six.PY3:
        s = s.decode('iso-8859-1')
    return s


def get_header(headers, name, default=None):
    """Return the value of header *name*.

    The *headers* argument must be a list of ``(name, value)`` tuples. If the
    header is found its associated value is returned, otherwise *default* is
    returned. Header names are matched case insensitively.
    """
    name = name.lower()
    for header in headers:
        if header[0].lower() == name:
            return header[1]
    return default

def remove_headers(headers, name):
    """Remove all headers with name *name*.

    The list is modified in-place and the updated list is returned.
    """
    i = 0
    name = name.lower()
    for j in range(len(headers)):
        if headers[j][0].lower() != name:
            if i != j:
                headers[i] = headers[j]
            i += 1
    del headers[i:]
    return headers


def create_chunk(buf):
    """Create a chunk for the HTTP "chunked" transfer encoding."""
    chunk = bytearray()
    chunk.extend(s2b('{:X}\r\n'.format(len(buf))))
    chunk.extend(s2b(buf))
    chunk.extend(b'\r\n')
    return chunk


def create_chunked_body_end(trailers=None):
    """Create the ending that terminates a chunked body."""
    ending = bytearray()
    ending.extend(b'0\r\n')
    if trailers:
        for name, value in trailers:
            ending.extend(s2b('{}: {}\r\n'.format(name, value)))
    ending.extend(b'\r\n')
    return ending


def create_request(version, method, url, headers):
    """Create a HTTP request header."""
    # According to my measurements using b''.join is faster that constructing a
    # bytearray.
    message = []
    message.append(s2b('{} {} HTTP/{}\r\n'.format(method, url, version)))
    for name, value in headers:
        message.append(s2b('{}: {}\r\n'.format(name, value)))
    message.append(b'\r\n')
    return b''.join(message)


def create_response(version, status, headers):
    """Create a HTTP response header."""
    message = []
    message.append(s2b('HTTP/{} {}\r\n'.format(version, status)))
    for name, value in headers:
        message.append(s2b('{}: {}\r\n'.format(name, value)))
    message.append(b'\r\n')
    return b''.join(message)


class HttpMessage(object):
    """HTTP message.

    Instances of this class are returned by :meth:`HttpClient.getresponse` and
    passed as an argument to :class:`HttpServer` message handlers.
    """

    def __init__(self):
        self._message_type = None
        self._version = None
        self._status_code = None
        self._method = None
        self._url = None
        self._parsed_url = None
        self._headers = []
        self._charset = None
        self._body = None
        self._should_keep_alive = None

    @property
    def message_type(self):
        """The message type, either :data:`REQUEST` or :data:`RESPONSE`."""
        return self._message_type

    @property
    def version(self):
        """The HTTP version as a string, either ``'1.0'`` or ``'1.1'``."""
        return self._version

    @property
    def status_code(self):
        """The HTTP status code as an integer. Only for response messages."""
        return self._status_code

    @property
    def method(self):
        """The HTTP method as a string. Only for request messages."""
        return self._method

    @property
    def url(self):
        """The URL as a string. Only for request messages."""
        return self._url

    @property
    def parsed_url(self):
        """The parsed URL as a :class:`ParsedUrl` instance."""
        return self._parsed_url

    @property
    def headers(self):
        """The headers as a list of ``(name, value)`` tuples."""
        return self._headers

    delegate_method(headers, get_header)

    @property
    def charset(self):
        """The character set as parsed from the "Content-Type" header, if available."""
        return self._charset

    @property
    def body(self):
        """The message body, as a :class:`~gruvi.Stream` instance."""
        return self._body


class HttpRequest(object):
    """HTTP client request.

    Usually you do not instantiate this class directly, but use the instance
    returned by :meth:`HttpProtocol.request`. You can however start new request
    yourself by instantiating this class and passing it a protocol instance.
    """

    def __init__(self, protocol):
        self._protocol = protocol
        self._content_length = None
        self._chunked = False
        self._bytes_written = 0
        self._charset = None

    @switchpoint
    def start_request(self, method, url, headers=None, bodylen=None):
        """Start a new HTTP request.

        The optional *headers* argument contains the headers to send. It must
        be a sequence of ``(name, value)`` tuples.

        The optional *bodylen* parameter is a hint that specifies the length of
        the body that will follow. A length of -1 indicates no body, 0 means an
        empty body, and a positive number indicates the body size in bytes.
        This parameter helps determine whether to use the chunked transfer
        encoding. Normally when the body size is known chunked encoding is not used.
        """
        self._headers = headers or []
        agent = host = clen = trailer = None
        # Check the headers provided, and capture some information about the
        # request from them.
        for name, value in self._headers:
            lname = name.lower()
            # Only HTTP applications are allowed to set "hop-by-hop" headers.
            if lname in hop_by_hop:
                raise ValueError('header {} is hop-by-hop'.format(name))
            elif lname == 'user-agent':
                agent = value
            elif lname == 'host':
                host = value
            elif lname == 'content-length':
                clen = int(value)
            elif lname == 'trailer':
                trailer = parse_trailer(value)
            elif lname == 'content-type' and value.startswith('text/'):
                ctype, params = parse_content_type(value)
                self._charset = params.get('charset')
        version = self._protocol._version
        # The Host header is mandatory in 1.1. Add it if it's missing.
        if host is None and version == '1.1':
            self._headers.append(('Host', self._protocol._server_name))
        # Identify ourselves.
        if agent is None:
            self._headers.append(('User-Agent', self._protocol.identifier))
        # Check if we need to use chunked encoding due to unknown body size.
        if clen is None and bodylen is None:
            if version == '1.0':
                raise HttpError('body size unknown for HTTP/1.0')
            self._chunked = True
        self._content_length = clen
        # Check if trailers are requested and if so need to switch to chunked.
        if trailer:
            if version == '1.0':
                raise HttpError('cannot support trailers for HTTP/1.0')
            if clen is not None:
                remove_headers(self._headers, 'Content-Length')
            self._chunked = True
        self._trailer = trailer
        # Add Content-Length if we know the body size and are not using chunked.
        if not self._chunked and clen is None and bodylen >= 0:
            self._headers.append(('Content-Length', str(bodylen)))
            self._content_length = bodylen
        # Complete the "Hop by hop" headers.
        if version == '1.0':
            self._headers.append(('Connection', 'keep-alive'))
        elif version == '1.1':
            self._headers.append(('Connection', 'te'))
            self._headers.append(('TE', 'trailers'))
        if self._chunked:
            self._headers.append(('Transfer-Encoding', 'chunked'))
        # Start the request
        self._protocol._requests.append(method)
        header = create_request(version, method, url, self._headers)
        self._protocol.writer.write(header)

    @switchpoint
    def write(self, buf):
        """Write *buf* to the request body."""
        if not isinstance(buf, six.binary_type):
            raise TypeError('buf: must be a bytes instance')
        # Be careful not to write zero-length chunks as they indicate the end of a body.
        if len(buf) == 0:
            return
        if self._content_length and self._bytes_written > self._content_length:
            raise RuntimeError('wrote too many bytes ({} > {})'
                                    .format(self._bytes_written, self._content_length))
        self._bytes_written += len(buf)
        if self._chunked:
            buf = create_chunk(buf)
        self._protocol.writer.write(buf)

    @switchpoint
    def end_request(self):
        """End the request body."""
        if not self._chunked:
            return
        trailers = [(n, get_header(self._headers, n)) for n in self._trailer] \
                        if self._trailer else None
        ending = create_chunked_body_end(trailers)
        self._protocol.writer.write(ending)


class ErrorStream(object):
    """Passed to the WSGI application as environ['wsgi.errors'].

    Forwards messages to the Python logging facility.
    """

    __slots__ = ['_log']

    def __init__(self, log=None):
        self._log = log or logging.get_logger()

    def flush(self):
        pass

    def write(self, data):
        self._log.error('wsgi.errors: {}', data)

    def writelines(self, seq):
        for line in seq:
            self.write(line)


class WsgiAdapter(object):
    """WSGI Adapter"""

    def __init__(self, application):
        """
        This class adapts the WSGI callable *application* so that instances of
        this class can be used as a message handler in :class:`HttpProtocol`.
        """
        self._application = application
        self._transport = None
        self._protocol = None
        self._log = logging.get_logger()

    @switchpoint
    def send_headers(self):
        # Send out the actual headers.
        # We need to figure out the transfer encoding of the body that will
        # follow the header. Here's what we do:
        #  - If we know the body length, don't use any TE.
        #  - Otherwise, if the protocol is HTTP/1.1, use "chunked".
        #  - Otherwise, close the connection after the body is sent.
        clen = get_header(self._headers, 'Content-Length')
        version = self._message.version
        # Keep the connection alive if the request wanted it kept alive AND we
        # can keep it alive because we don't need EOF to signal end of message.
        can_chunk = version == '1.1'
        can_keep_alive = can_chunk or clen is not None or self._body_len is not None
        self._keepalive = self._message._should_keep_alive and can_keep_alive
        # The default on HTTP/1.1 is keepalive, on HTTP/1.0 it is to close.
        if version == '1.1' and not self._keepalive:
            self._headers.append(('Connection', 'close'))
        elif version == '1.0' and self._keepalive:
            self._headers.append(('Connection', 'keep-alive'))
        # Are we using chunked?
        self._chunked = can_chunk and clen is None and self._body_len is None
        if self._chunked:
            self._headers.append(('Transfer-Encoding', 'chunked'))
        elif clen is None and self._body_len is not None:
            self._headers.append(('Content-Length', str(self._body_len)))
        # Trailers..
        trailer = get_header(self._headers, 'Trailer')
        te = get_header(self._message.headers, 'TE')
        if version == '1.1' and trailer is not None and te is not None:
            tenames = [e[0].lower() for e in parse_te(te)]
            if 'trailers' in tenames:
                trailer = parse_trailer(trailer)
            else:
                remove_headers(self._headers, 'Trailer')
        self._trailer = trailer
        # Add some informational headers.
        server = get_header(self._headers, 'Server')
        if server is None:
            self._headers.append(('Server', self._protocol.identifier))
        date = get_header(self._headers, 'Date')
        if date is None:
            self._headers.append(('Date', rfc1123_date()))
        header = create_response(version, self._status, self._headers)
        self._protocol.writer.write(header)
        self._headers_sent = True

    def start_response(self, status, headers, exc_info=None):
        # Callable to be passed to the WSGI application.
        if exc_info:
            try:
                if self._headers_sent:
                    six.reraise(*exc_info)
            finally:
                exc_info = None
        elif self._status is not None:
            raise RuntimeError('response already started')
        for name, value in headers:
            if name.lower() in hop_by_hop:
                raise ValueError('header {} is hop-by-hop'.format(name))
        self._status = status
        self._headers = headers
        return self.write

    @switchpoint
    def write(self, data):
        # Callable passed to the WSGI application by start_response().
        if not isinstance(data, bytes):
            raise TypeError('data: expecting bytes instance')
        # Never write empty chunks as they signal end of body.
        if not data:
            return
        if not self._status:
            raise HttpError('WSGI handler did not call start_response()')
        if not self._headers_sent:
            self.send_headers()
        if self._chunked:
            data = create_chunk(data)
        self._protocol.writer.write(data)

    @switchpoint
    def end_response(self):
        # Finalize a response. This method must be called.
        if not self._status:
            raise HttpError('WSGI handler did not call start_response()')
        if not self._headers_sent:
            self._body_len = 0
            self.send_headers()
        if self._chunked:
            trailers = [hd for hd in self._headers if hd[0] in self._trailer] \
                            if self._trailer else None
            ending = create_chunked_body_end(trailers)
            self._protocol.writer.write(ending)
        if not self._keepalive:
            self._transport.close()

    @switchpoint
    def __call__(self, message, transport, protocol):
        # Run the WSGI handler.
        self._message = message
        if self._transport is None:
            self._transport = transport
            self._protocol = protocol
            self._sockname = transport.get_extra_info('sockname')
            self._peername = transport.get_extra_info('peername')
        self._status = None
        self._headers = None
        self._headers_sent = False
        self._chunked = False
        self._body_len = None
        self.create_environ()
        self._log.debug('request: {} {}', message.method, message.url)
        result = None
        try:
            result = self._application(self._environ, self.start_response)
            # Prevent chunking in this common case:
            if isinstance(result, list) and len(result) == 1:
                self._body_len = len(result[0])
            for chunk in result:
                self.write(chunk)
            self.end_response()
        finally:
            if hasattr(result, 'close'):
                result.close()
        ctype = get_header(self._headers, 'Content-Type', 'unknown')
        clen = get_header(self._headers, 'Content-Length', 'unknown')
        self._log.debug('response: {} ({}; {} bytes)'.format(self._status, ctype, clen))

    def create_environ(self):
        # Initialize the environment with per connection variables.
        m = self._message
        env = self._environ = {}
        # CGI variables
        env['SCRIPT_NAME'] = ''
        if isinstance(self._sockname, tuple):
            env['SERVER_NAME'] = self._protocol._server_name or self._sockname[0]
            env['SERVER_PORT'] = str(self._sockname[1])
        else:
            env['SERVER_NAME'] = self._protocol._server_name or self._sockname
            env['SERVER_PORT'] = ''
        env['SERVER_SOFTWARE'] = self._protocol.identifier
        env['SERVER_PROTOCOL'] = 'HTTP/' + m.version
        env['REQUEST_METHOD'] = m.method
        env['PATH_INFO'] = m.parsed_url[2]
        env['QUERY_STRING'] = m.parsed_url[4]
        env['REQUEST_URI'] = m.url
        for name, value in m.headers:
            if name.lower() in hop_by_hop:
                continue
            name = name.upper().replace('-', '_')
            if name not in ('CONTENT_LENGTH', 'CONTENT_TYPE'):
                name = 'HTTP_' + name
            env[name] = value
        # SSL information
        sslobj = self._transport.get_extra_info('ssl')
        cipherinfo = sslobj.cipher() if sslobj else None
        if sslobj and cipherinfo:
            env['HTTPS'] = '1'
            env['SSL_CIPHER'] = cipherinfo[0]
            env['SSL_PROTOCOL'] = cipherinfo[1]
            env['SSL_CIPHER_USEKEYSIZE'] = int(cipherinfo[2])
        # Support the de-facto X-Forwarded-For and X-Forwarded-Proto headers
        # that are added by reverse proxies.
        peername = self._transport.get_extra_info('peername')
        remote = env.get('HTTP_X_FORWARDED_FOR')
        env['REMOTE_ADDR'] = remote if remote else peername[0] \
                                        if isinstance(peername, tuple) else ''
        proto = env.get('HTTP_X_FORWARDED_PROTO')
        env['REQUEST_SCHEME'] = proto if proto else 'https' if sslobj else 'http'
        # WSGI specific variables
        env['wsgi.version'] = (1, 0)
        env['wsgi.url_scheme'] = env['REQUEST_SCHEME']
        env['wsgi.input'] = m.body
        env['wsgi.errors'] = ErrorStream(self._log)
        env['wsgi.multithread'] = True
        env['wsgi.multiprocess'] = True
        env['wsgi.run_once'] = False
        env['wsgi.charset'] = m.charset
        # Gruvi specific variables
        env['gruvi.sockname'] = self._sockname
        env['gruvi.peername'] = self._peername


class HttpProtocol(MessageProtocol):
    """HTTP protocol implementation."""

    identifier = __name__

    #: Default HTTP version.
    default_version = '1.1'

    #: Max header size. The parser keeps the header in memory during parsing.
    max_header_size = 65536

    #: Max number of body bytes to buffer. Bodies larger than this will cause
    #: the transport to be paused until the buffer is below the threshold again.
    max_buffer_size = 65536

    #: Max number of pipelined requests to keep before pausing the transport.
    max_pipeline_size = 10

    # In theory, max memory is pipeline_size * (header_size + buffer_size)

    def __init__(self, handler=None, server_side=False, server_name=None,
                 version=None, timeout=None):
        """
        The *handler* argument specifies a message handler to handle incoming
        HTTP requests. It must be a callable with the signature
        ``handler(message, transport, protocol)``.

        The *server_side* argument specifies whether this is a client or server
        side protocol. For server-side protocols, the *server_name* argument
        can be used to provide a server name. If not provided, then the socket
        name of the listening socket will be used.
        """
        super(HttpProtocol, self).__init__(handler, timeout=timeout)
        if server_side and handler is None:
            raise ValueError('need a handler for server side protocol')
        self._handler = handler
        self._server_side = server_side
        self._server_name = server_name
        self._version = self.default_version if version is None else version
        if self._version not in ('1.0', '1.1'):
            raise ValueError('unsupported HTTP version: {!r}'.format(version))
        self._timeout = timeout
        self._create_parser()
        self._requests = []
        self._response = None
        self._writer = None
        self._message = None
        self._error = None

    def _create_parser(self):
        # Create a new CFFI http and parser.
        self._parser = ffi.new('http_parser *')
        self._cdata = ffi.new_handle(self)  # store in instance to keep alive:
        self._parser.data = self._cdata     # struct field doesn't take reference
        kind = lib.HTTP_REQUEST if self._server_side else lib.HTTP_RESPONSE
        lib.http_parser_init(self._parser, kind)
        self._urlparser = ffi.new('struct http_parser_url *')

    def _append_header_name(self, buf):
        # Add a chunk to a header name.
        if self._header_value:
            # This starts a new header: stash away the previous one.
            # The header might be part of the http headers or trailers.
            header = (ba2s(self._header_name), ba2s(self._header_value))
            self._message.headers.append(header)
            # Try to capture the charset for text bodies.
            if header[0].lower() == 'content-type':
                ctype, params = parse_content_type(header[1])
                if ctype.startswith('text/'):
                    self._message._charset = params.get('charset')
            del self._header_name[:]
            del self._header_value[:]
        self._header_name.extend(buf)

    def _append_header_value(self, buf):
        # Add a chunk to a header value.
        self._header_value.extend(buf)

    # Parser callbacks. These are Python methods called by http-parser C code
    # via CFFI. Callbacks are run in the hub fiber, and we only do parsing
    # here, no handlers are run. For server protocols we stash away the result
    # in a queue to be processed in a dispatcher fiber (one per protocol).
    #
    # Callbacks return 0 for success, 1 for error.
    #
    # Also note that these are static methods that get a reference to their
    # instance via the parser state (parser.data).

    @ffi.callback('http_cb')
    def on_message_begin(parser):
        # http-parser callback: prepare for a new message
        self = ffi.from_handle(parser.data)
        self._url = bytearray()
        self._header = bytearray()
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._header_size = 0
        self._message = HttpMessage()
        lib.http_parser_url_init(self._urlparser)
        return 0

    @ffi.callback('http_data_cb')
    def on_url(parser, at, length):
        # http-parser callback: got a piece of the URL
        self = ffi.from_handle(parser.data)
        self._header_size += length
        if self._header_size > self.max_header_size:
            self._error = HttpError('HTTP header too large')
            return 1
        self._url.extend(ffi.buffer(at, length))
        return 0

    @ffi.callback('http_data_cb')
    def on_header_name(parser, at, length):
        # http-parser callback: got a piece of a header name
        self = ffi.from_handle(parser.data)
        self._header_size += length
        if self._header_size > self.max_header_size:
            self._error = HttpError('HTTP header too large')
            return 1
        buf = ffi.buffer(at, length)
        self._append_header_name(buf)
        return 0

    @ffi.callback('http_data_cb')
    def on_header_value(parser, at, length):
        # http-parser callback: got a piece of a header value
        self = ffi.from_handle(parser.data)
        self._header_size += length
        if self._header_size > self.max_header_size:
            self._error = HttpError('HTTP header too large')
            return 1
        buf = ffi.buffer(at, length)
        self._append_header_value(buf)
        return 0

    @ffi.callback('http_cb')
    def on_headers_complete(parser):
        # http-parser callback: the HTTP header is complete. This is the point
        # where we hand off the message to our consumer. Going forward,
        # on_body() will continue to write chunks of the body to message.body.
        self = ffi.from_handle(parser.data)
        self._append_header_name(b'')
        m = self._message
        m._message_type = lib.http_message_type(parser)
        m._version = '{}.{}'.format(parser.http_major, parser.http_minor)
        if self._server_side:
            m._method = _http_methods.get(lib.http_method(parser), '<unknown>')
            m._url = ba2s(self._url)
            res = lib.http_parser_parse_url(ffi.from_buffer(self._url), len(self._url),
                                            m._method == 'CONNECT', self._urlparser)
            assert res == 0   # URL was already validated by http-parser
            m._parsed_url = ParsedUrl.from_parser(self._urlparser, m._url)
        else:
            m._status_code = lib.http_status_code(parser)
        m._should_keep_alive = lib.http_should_keep_alive(parser)
        m._body = Stream(self._transport, 'r')
        m._body.buffer.set_buffer_limits(self.max_buffer_size)
        # Make the message available on the queue.
        self._queue.put_nowait(m)
        # Return 1 if this is a response to a HEAD request. This is a hint to
        # the parser that no body will follow. Normally the parser deduce from
        # the headers whether body will follow (either Content-Length or
        # Transfer-Encoding is present). But not so with HEAD, as the response
        # is exactly identical to GET but without the body.
        if not self._server_side and self._requests and self._requests.pop(0) == 'HEAD':
            return 1
        return 0

    @ffi.callback('http_data_cb')
    def on_body(parser, at, length):
        # http-parser callback: got a body chunk
        self = ffi.from_handle(parser.data)
        # StreamBuffer.feed() may pause the transport here if the buffer size is exceeded.
        self._message.body.buffer.feed(bytes(ffi.buffer(at, length)))
        return 0

    @ffi.callback('http_cb')
    def on_message_complete(parser):
        # http-parser callback: the http request or response ended
        # complete any trailers that might be present
        self = ffi.from_handle(parser.data)
        self._append_header_name(b'')
        self._message.body.buffer.feed_eof()
        self._maybe_pause_transport()
        return 0

    # The settings object is shared between all protocol instances.

    _settings = ffi.new('http_parser_settings *')
    _settings.on_message_begin = on_message_begin
    _settings.on_url = on_url
    _settings.on_header_field = on_header_name
    _settings.on_header_value = on_header_value
    _settings.on_headers_complete = on_headers_complete
    _settings.on_body = on_body
    _settings.on_message_complete = on_message_complete

    def connection_made(self, transport):
        # Protocol callback
        super(HttpProtocol, self).connection_made(transport)
        self._transport = transport
        self._writer = Stream(transport, 'w')

    def data_received(self, data):
        # Protocol callback
        nbytes = lib.http_parser_execute(self._parser, self._settings, data, len(data))
        if nbytes != len(data):
            msg = cd2s(lib.http_errno_name(lib.http_errno(self._parser)))
            self._log.debug('http_parser_execute(): {}'.format(msg))
            self._error = HttpError('parse error: {}'.format(msg))
            if self._message:
                self._message.body.buffer.feed_error(self._error)
            self._transport.close()

    def connection_lost(self, exc):
        # Protocol callback
        # Feed the EOF to the parser. It will tell us it if was unexpected.
        super(HttpProtocol, self).connection_lost(exc)
        nbytes = lib.http_parser_execute(self._parser, self._settings, b'', 0)
        if nbytes != 0:
            msg = cd2s(lib.http_errno_name(lib.http_errno(self._parser)))
            self._log.debug('http_parser_execute(): {}'.format(msg))
            if exc is None:
                exc = HttpError('parse error: {}'.format(msg))
            if self._message:
                self._message.body.buffer.feed_error(exc)
        self._error = exc

    @property
    def writer(self):
        """A :class:`~gruvi.Stream` instance for writing directly to the
        underlying transport."""
        return self._writer

    @switchpoint
    def request(self, method, url, headers=None, body=None):
        """Make a new HTTP request.

        The *method* argument is the HTTP method as a string, for example
        ``'GET'`` or ``'POST'``. The *url* argument specifies the URL.

        The optional *headers* argument specifies extra HTTP headers to use in
        the request. It must be a sequence of ``(name, value)`` tuples.

        The optional *body* argument may be used to include a body in the
        request. It must be a ``bytes`` instance, a file-like object opened in
        binary mode, or an iterable producing ``bytes`` instances.  To send
        potentially large bodies, use the file or iterator interfaces. This has
        the benefit that only a single chunk is kept in memory at a time.

        The response to the request can be obtained by calling the
        :meth:`getresponse` method. You may make multiple requests before
        reading a response. For every request that you make however, you must
        call :meth:`getresponse` exactly once. The remote HTTP implementation
        will send by the responses in the same order as the requests.

        This method will use the "chunked" transfer encoding if here is a body
        and the body size is unknown ahead of time. This happens when the file
        or interator interface is used in the abence of a "Content-Length"
        header.
        """
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._transport is None:
            raise HttpError('not connected')
        request = HttpRequest(self)
        bodylen = -1 if body is None else \
                        len(body) if isinstance(body, bytes) else None
        request.start_request(method, url, headers, bodylen)
        if isinstance(body, bytes):
            request.write(body)
        elif hasattr(body, 'read'):
            while True:
                chunk = body.read(4096)
                if not chunk:
                    break
                request.write(chunk)
        elif hasattr(body, '__iter__'):
            for chunk in body:
                request.write(chunk)
        request.end_request()

    @switchpoint
    def getresponse(self):
        """Wait for and return a HTTP response.

        The return value will be a :class:`HttpMessage`. When this method
        returns only the response header has been read. The response body can
        be read using :meth:`~gruvi.Stream.read` and similar methods on
        the message :attr:`~HttpMessage.body`.

        Note that if you use persistent connections (the default), it is
        required that you read the entire body of each response. If you don't
        then deadlocks may occur.
        """
        if self._error:
            raise compat.saved_exc(self._error)
        elif self._transport is None:
            raise HttpError('not connected')
        message = self._queue.get(timeout=self._timeout)
        if isinstance(message, Exception):
            raise compat.saved_exc(message)
        return message


class HttpClient(Client):
    """HTTP client."""

    def __init__(self, version=None, timeout=None):
        """
        The optional *version* argument specifies the HTTP version to use. The
        default is :attr:`HttpProtocol.default_version`.

        The optional *timeout* argument specifies the timeout for various
        network and protocol operations.
        """
        protocol_factory = functools.partial(HttpProtocol, version=version)
        super(HttpClient, self).__init__(protocol_factory, timeout=timeout)
        self._server_name = None

    @docfrom(Client.connect)
    def connect(self, address, **kwargs):
        # Capture the host name that we are connecting to. We need this for
        # generating "Host" headers in HTTP/1.1
        if self._server_name is None and isinstance(address, tuple):
            host, port = address[:2]  # len(address) == 4 for IPv6
            if port != default_ports['https' if 'ssl' in kwargs else 'http']:
                host = '{}:{}'.format(host, port)
            self._server_name = host
        super(HttpClient, self).connect(address, **kwargs)
        self._protocol._server_name = self._server_name

    protocol = Client.protocol

    delegate_method(protocol, HttpProtocol.request)
    delegate_method(protocol, HttpProtocol.getresponse)


class HttpServer(Server):
    """HTTP server."""

    #: The default adapter to use.
    default_adapter = WsgiAdapter

    def __init__(self, application, server_name=None, adapter=None, timeout=None):
        """The *application* argument is the web application to expose on this
        server. The application is wrapped in *adapter* to create a message
        handler as required by :class:`HttpProtocol`. By default the adapter in
        :attr:`default_adapter` is used.

        The optional *server_name* argument specifies the server name. The
        default is to use the host portion of the address passed to
        :meth:`~gruvi.Server.listen`. The server name is made available to WSGI
        applications as the $SERVER_NAME environment variable.

        The optional *timeout* argument specifies the timeout for various
        network and protocol operations.
        """
        adapter = self.default_adapter if adapter is None else adapter
        def handler(*args):
            return adapter(application)(*args)
        protocol_factory = functools.partial(HttpProtocol, handler,
                                             server_side=True, server_name=server_name)
        super(HttpServer, self).__init__(protocol_factory, timeout)
        self._server_name = server_name

    def connection_made(self, transport, protocol):
        if protocol._server_name is None:
            protocol._server_name = self._server_name

    def listen(self, address, **kwargs):
        # Capture the first listen address to provide for a default server name.
        if not self._server_name and isinstance(address, tuple):
            host, port = address[:2]  # len(address) == 4 for IPv6
            if port != default_ports['https' if 'ssl' in kwargs else 'http']:
                host = '{}:{}'.format(host, port)
            self._server_name = host
        super(HttpServer, self).listen(address, **kwargs)
