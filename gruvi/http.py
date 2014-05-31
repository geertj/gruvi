#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

"""
The :mod:`gruvi.http` module implements a HTTP client and server.

The client and server are relatively complete implementations of the HTTP
protocol. Some of the supported features are: keepalive, pipelining, chunked
transfers and trailers.

Some general notes about the implementation:

* Both HTTP/1.0 and HTTP/1.1 are supported. The client will by default make
  requests with HTTP/1.1. The server always responds in the same version as the
  request.
* Connections are kept alive by default. This means that you need to make sure
  you close connections when they are no longer needed.
* Any headers that are passed in by application code must not be "Hop by hop"
  headers. These headers may only be used by HTTP implementations themselves,
  such as the client and server in this module.

Some important points about the use of binary versus unicode types in the API:

* Data that is passed into the API that ends up in the HTTP header, such as the
  HTTP version string, method, and headers, must be of the string type. This
  means ``str`` on Python 3, and ``str`` or ``unicode`` on Python 2. However,
  if the string type is unicode aware (all except ``str`` on Python 2), you
  must make sure that it only contains code points that are defined in
  ISO-8859-1, which is the default HTTP encoding specified in RFC2606.
* In theory, HTTP headers can support unicode code points outside ISO-8859-1 if
  encoded according to the scheme in RFC2047. However this method is very
  poorly supported and rarely used, and Gruvi therefore does not offer any
  special support for it. If you must use this feature for some reason, you can
  pre-encode the headers into this encoding and pass them already encoded.
* Data that is passed to the API and ends up in the HTTP body can be either of
  the binary type or of the string type (``bytes``, ``str`` or ``unicode``, the
  latter only on Python 2). If passing a unicode aware type, then the data is
  encoded before adding it to the body. The encoding must be passed into the
  client or server by passing a "Content-Type" header with a "charset"
  parameter. If no encoding is provided, then ISO-8859-1 is assumed. Note that
  ISO-8859-1 is not able to express any code points outside latin1. This means
  that if you pass a body with non-latin1 code points, and you fail to set the
  "charset" parameter, then you will get a ``UnicodeEncodeError`` exception.
"""

from __future__ import absolute_import, print_function

import re
import time
import six

from . import logging
from .hub import switchpoint
from .util import docfrom
from .errors import Error
from .protocols import MessageProtocol
from .endpoints import Client, Server, add_protocol_method
from .stream import StreamReader
from .http_ffi import lib as _lib, ffi as _ffi
from ._version import version_info

from six.moves import http_client

__all__ = ['HttpError', 'HttpClient', 'HttpServer']


# Export some definitions from  http.client.
for name in dir(http_client):
    value = getattr(http_client, name)
    if name.isupper() and value in http_client.responses:
        globals()[name] = value

HTTP_PORT = http_client.HTTP_PORT
HTTPS_PORT = http_client.HTTPS_PORT
responses = http_client.responses


# The "Hop by Hop" headers as defined in RFC 2616. These may not be set by the
# HTTP handler.
hop_by_hop = frozenset(('connection', 'keep-alive', 'proxy-authenticate',
                        'proxy-authorization', 'te', 'trailers',
                        'transfer-encoding', 'upgrade'))


# URL fields as defined by the http-parser URL parser.
_url_fields = (_lib.UF_SCHEMA, _lib.UF_HOST, _lib.UF_PORT, _lib.UF_PATH,
               _lib.UF_QUERY, _lib.UF_FRAGMENT, _lib.UF_USERINFO)


def parse_url(url, is_connect=False):
    """Split a URL into its components.

    This function is similar to :func:`urllib.parse.urlsplit` but it uses the
    http-parser URL splitter via CFFI.

    The return value is a sequence: (scheme, host, port, path, query, fragment,
    userinfo).
    """
    if isinstance(url, six.text_type):
        url = url.encode('iso-8859-1')
    elif hasattr(url, 'tobytes'):
        url = url.tobytes()
    elif not isinstance(url, bytes):
        url = bytes(url)
    result = _ffi.new('struct http_parser_url *')
    error = _lib.http_parser_parse_url(url, len(url), is_connect, result)
    if error:
        raise ValueError('http_parser_parse_url(): could not parse')
    parsed = []
    for field in _url_fields:
        if result.field_set & (1 << field):
            span = result.field_data[field]
            comp = url[span.off:span.off+span.len].decode('iso-8859-1')
        else:
            comp = ''
        parsed.append(comp)
    return parsed


# RFC 2626 section 2.2 grammar definitions:
_re_token = re.compile('([!#$%&\'*+-.0-9A-Z^_`a-z|~]+)')

# The regex for "quoted_string" below is not 100% correct. The standard allows
# also LWS and escaped CTL characters. But http-parser has an issue with these
# so we just not allow them.
# Note that the first 256 code points of Unicode are the same as those for
# ISO-8859-1 which is how HTTP headers are encoded. So we can just include the
# valid characters as \x hex references.
# Also note that this does not decode any of the RFC-2047 internationalized
# header values that are allowed in quoted-string (but it will match).
_re_qstring = re.compile('"(([ !\x23-\xff]|\\")*)"')


def parse_option_header(header, sep=';'):
    """Parse a HTTP header with options.

    The header must be of the form "value [; parameters]". This format is used
    by headers like "Content-Type" and "Transfer-Encoding".

    The return value is a (value, params) tuple, with params a dictionary
    containing the parameters.

    This function never raises an error. When a parse error occurs, it returns
    what has been parsed so far.
    """
    options = {}
    p1 = header.find(sep)
    if p1 == -1:
        return header, options
    p2 = p1+1
    while True:
        while p2 < len(header) and header[p2].isspace():
            p2 += 1
        if p2 == len(header):
            break
        mobj = _re_token.match(header, p2)
        if mobj is None:
            break
        name = mobj.group(1)
        p2 = mobj.end(0)
        if p2 > len(header)-2 or header[p2] != '=':
            break
        p2 += 1
        if header[p2] == '"':
            mobj = _re_qstring.match(header, p2)
        else:
            mobj = _re_token.match(header, p2)
        if mobj is None:
            break
        value = mobj.group(1)
        p2 = mobj.end(0)
        options[name] = value
    return header[:p1], options


_weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
_rfc1123_fmt = '%a, %d %b %Y %H:%M:%S GMT'

def rfc1123_date(timestamp=None):
    """Create a RFC1123 style Date header for *timestamp*.

    If *timestamp* is None, use the current time.
    """
    if timestamp is None:
        timestamp = time.time()
    tm = time.gmtime(timestamp)
    # The time stamp must be GMT, and cannot be localized
    s = _rfc1123_fmt.replace('%a', _weekdays[tm.tm_wday]) \
                    .replace('%b', _months[tm.tm_mon-1])
    return time.strftime(s, tm)


def _s2b(s):
    """Convert a string *s* to bytes in the ISO-8859-1 encoding.

    ISO-8859-1 is the default encoding used in HTTP.
    """
    if type(s) is not bytes:
        s = s.encode('iso-8859-1')
    return s

def _ba2s(ba):
    """Convert a byte-array to a "str" type."""
    if six.PY3:
        return ba.decode('iso-8859-1')
    else:
        return bytes(ba)

def _cd2s(cd):
    """Convert a cffi cdata('char *') to a str."""
    s = _ffi.string(cd)
    if six.PY3:
        s = s.decode('iso-8859-1')
    return s


def get_field(headers, name, default=None):
    """Return a field value from a list with (name, value) tuples."""
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


def create_chunked_body_end(trailers=None):
    """Create the ending that terminates a chunked body."""
    ending = bytearray()
    ending.extend(b'0\r\n')
    if trailers:
        for name, value in trailers:
            ending.extend(_s2b('{0}: {1}\r\n'.format(name, value)))
    ending.extend(b'\r\n')
    return ending


def create_request(version, method, url, headers):
    """Create a HTTP request header."""
    message = bytearray()
    message.extend(_s2b('{0} {1} HTTP/{2}\r\n'.format(method, url, version)))
    for name, value in headers:
        message.extend(_s2b('{0}: {1}\r\n'.format(name, value)))
    message.extend(b'\r\n')
    return message


def create_response(version, status, headers):
    """Create a HTTP response header."""
    message = bytearray()
    message.extend(_s2b('HTTP/{0} {1}\r\n'.format(version, status)))
    for name, value in headers:
        message.extend(_s2b('{0}: {1}\r\n'.format(name, value)))
    message.extend(b'\r\n')
    return message


class HttpError(Error):
    """Exception that is raised in case of HTTP protocol errors."""


class HttpMessage(object):
    """A HTTP message (request or response).

    This is an internal class used by the parser.
    """

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
        self.body = None


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


class HttpRequest(object):
    """A HTTP request.

    Instances of this class are returned by :meth:`HttpProtocol.request` when
    you set the *body* parameter to ``None``.

    This class allows you to write the request body yourself using the
    :meth:`write` and :meth:`end_request` methods. This can be useful if you
    need to send a large input that cannot be easily presented as as a
    file-like object or a generator, or if you want to use "chunked" encoding
    trailers.
    """

    def __init__(self, transport, protocol):
        self._transport = transport
        self._protocol = protocol
        self._chunked = False
        self._charset = 'ISO-8859-1'
        self._content_length = None
        self._bytes_written = 0

    def start_request(self, method, url, headers=None, body=None):
        """Start a new HTTP request.

        This method is called by :meth:`HttpProtocol.request`. It creates a new
        HTTP request header and sends it to the transport.

        The *body* parameter is a hint that specifies the body that will be
        sent in the future, but it will not actually send it. This method tries
        to deduce the Content-Length of the body that follows from it.
        """
        headers = headers[:] if headers is not None else []
        agent = host = clen = ctype = None
        # Ensure that the user doesn't provide any hop-by-hop headers. Only
        # HTTP applications are allowed to set these.
        for name, value in headers:
            name = name.lower()
            if name in hop_by_hop:
                raise ValueError('header {0} is hop-by-hop'.format(name))
            elif name == 'user-agent':
                agent = value
            elif name == 'host':
                host = value
            elif name == 'content-type':
                ctype, params = parse_option_header(value)
                self._charset = params.get('charset')
            elif name == 'content-length':
                clen = int(value)
        # Check that we can support the body type.
        if not isinstance(body, (six.binary_type, six.text_type)) \
                    and not hasattr(body, 'read') \
                    and not hasattr(body, '__iter__') \
                    and body is not None:
            raise TypeError('body: expecting a bytes or str instance, '
                            'a file-like object or an iterable')
        version = self._protocol._version
        # The Host header is mandatory in 1.1. Add it if it's missing.
        server_name = self._protocol.server_name
        if host is None and version == '1.1' and server_name:
            headers.append(('Host', server_name))
        # Identify ourselves.
        if agent is None:
            headers.append(('User-Agent', self._protocol.identifier))
        # Check if we know the body length. If not, then we require "chunked"
        # encoding. Then determine if we can keep the connection alive.
        if isinstance(body, six.text_type):
            body = body.encode(self._charset)
        if clen is None:
            if isinstance(body, six.binary_type):
                clen = len(body)
                if clen > 0:
                    headers.append(('Content-Length', str(clen)))
            elif version == '1.1':
                self._chunked = True
            else:
                raise ValueError('headers: must have "Content-Length" header '
                                 'for HTTP 1.0 when body size unknown')
        self._content_length = clen
        # On HTTP/1.0 we need to specifically indicate we want keep-alive.
        if version == '1.0':
            headers.append(('Connection', 'keep-alive'))
        # If we're doing chunked then we can also do trailers.
        if self._chunked:
            headers.append(('Transfer-Encoding', 'chunked'))
            headers.append(('TE', 'trailers'))
        # Start the request
        header = create_request(version, method, url, headers)
        self._protocol.write(header)

    def write(self, buf):
        """Write *buf* to the request body."""
        if not buf:
            return
        if isinstance(buf, six.text_type):
            buf = buf.encode(self._charset)
        self._bytes_written += len(buf)
        if self._content_length is not None and self._bytes_written > self._content_length:
            raise RuntimeError('wrote too many bytes ({0} > {1})'
                                    .format(self._bytes_written, self._content_length))
        if self._chunked:
            buf = create_chunk(buf)
        self._protocol.write(buf)

    def end_request(self, trailers=None):
        """End the request body.

        The optional *trailers* argument can be used to add trailers. This
        requires "chunked" encoding.
        """
        if trailers and not self._chunked:
            raise RuntimeError('trailers require "chunked" encoding')
        if self._chunked:
            ending = create_chunked_body_end(trailers)
            self._protocol.write(ending)


class HttpResponse(object):
    """An HTTP response as returned by :meth:`HttpClient.get_response`."""

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
        """Return the value of HTTP header *name*.

        If the header does not exist, return *default*.
        """
        return get_field(self._message.headers, name, default)

    def get_trailer(self, name, default=None):
        """Return a the value of a HTTP trailer *name*.

        If the trailer does not exist, return *default*.
        """
        return get_field(self._message.trailers, name, default)

    @switchpoint
    def read(self, size=-1):
        """Read up to *size* bytes from the response body.

        If *size* is not specified or negative, read the entire body.
        """
        return self._message.body.read(size)

    @switchpoint
    def readline(self, limit=-1):
        """Read a single line from the response body.

        If the end of the body is reached before an entire line could be read,
        a partial line is returned. If *limit* is specified, at most this many
        bytes will be read.
        """
        return self._message.body.readline(limit)

    @switchpoint
    @docfrom(StreamReader.readlines)
    def readlines(self, hint=-1):
        """Read the response body and return it as a list of lines.

        If *hint* is specified, then lines will be read until their combined
        size will be equal or larger than *hint*, or until the end of the body
        is reached, whichever happens first.
        """
        return self._message.body.readlines(hint)

    @property
    def __iter__(self):
        """Generate lines from the response body."""
        return self._message.body.__iter__


class WsgiHandler(object):
    """An adapter that runs a WSGI application as a :class:`MessageProtocol`
    message handler.

    This class is used internally by :class:`HttpProtocol`.
    """

    def __init__(self, application):
        """
        The *transport* and *protocol* arguments are the connection's
        transport and protocol respectively.

        The *message* argument must be a :class:`HttpMessage`.
        """
        self._application = application
        self._transport = None
        self._protocol = None
        self._message = None
        self._log = logging.get_logger()
        self._environ = {}
        self._status = None
        self._headers = None
        self._prev_body = None

    def send_headers(self):
        """Send the HTTP headers and start the response body."""
        # We need to figure out the transfer encoding of the body that will
        # follow the header. Here's what we do:
        #  - If there's a content length, don't use any TE.
        #  - Otherwise, if the protocol is HTTP/1.1, use "chunked".
        #  - Otherwise, close the connection after the body is sent.
        clen = get_field(self._headers, 'Content-Length')
        version = self._message.version
        self._chunked = clen is None and version == '1.1'
        if self._chunked:
            self._headers.append(('Transfer-Encoding', 'chunked'))
        # The client may also ask to close the connection (Connection: close)
        self._keepalive = self._message.should_keep_alive and (self._chunked or clen)
        # The default on HTTP/1.1 is keepalive, on HTTP/1.0 it is to close.
        if version == 'HTTP/1.1' and not self._keepalive:
            self._headers.append(('Connection', 'close'))
        elif version == 'HTTP/1.0' and self._keepalive:
            self._headers.append(('Connection', 'keep-alive'))
        server = get_field(self._headers, 'Server')
        if server is None:
            self._headers.append(('Server', self._protocol.identifier))
        date = get_field(self._headers, 'Date')
        if date is None:
            self._headers.append(('Date', rfc1123_date()))
        header = create_response(version, self._status, self._headers)
        self._protocol.write(header)

    def start_response(self, status, headers, exc_info=None):
        """Callable to be passed to the WSGI application."""
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
                raise ValueError('header {0} is hop-by-hop'.format(name))
        self._status = status
        self._headers = headers
        return self.write

    def write(self, data):
        """Callable passed to the WSGI application by :meth:`start_response`."""
        if isinstance(data, six.text_type):
            data = data.encode('iso-8859-1')
        elif not isinstance(data, six.binary_type):
            raise TypeError('data: expecting bytes or str instance')
        elif not data:
            return
        if not self._headers_sent:
            self.send_headers()
            self._headers_sent = True
        if self._chunked:
            data = create_chunk(data)
        self._protocol.write(data)

    def end_response(self):
        """End a response."""
        if not self._headers_sent:
            self.send_headers()
            self._headers_sent = True
        if self._chunked:
            trailers = self._environ.get('gruvi.trailers')
            ending = create_chunked_body_end(trailers)
            self._protocol.write(ending)
        if not self._message.should_keep_alive:
            self._transport.close()

    def __call__(self, message, transport, protocol):
        """Run a WSGI handler."""
        if self._transport is None:
            self._transport = transport
            self._protocol = protocol
        if self._prev_body and not self._prev_body.eof:
            self._log.error('body not fully read pipelined request, closing connection')
            self._transport.close()
            return
        self._status = None
        self._headers = None
        self._headers_sent = False
        self._chunked = False
        self._message = message
        self.create_environ()
        self._log.debug('request: {} {}', message.method, message.url)
        result = None
        try:
            result = self._application(self._environ, self.start_response)
            if not self._status:
                raise HttpError('WSGI handler did not call start_response()')
            for chunk in result:
                self.write(chunk)
            self.end_response()
        finally:
            self._prev_body = self._message.body
            if hasattr(result, 'close'):
                result.close()
        ctype = get_field(self._headers, 'Content-Type', 'unknown')
        clen = get_field(self._headers, 'Content-Length', 'unknown')
        self._log.debug('response: {0} ({1}; {2} bytes)'.format(self._status, ctype, clen))

    def create_environ(self):
        # Initialize the environment with per connection variables.
        m = self._message
        env = self._environ
        # CGI variables
        env['SCRIPT_NAME'] = ''
        sockname = self._transport.get_extra_info('sockname')
        if isinstance(sockname, tuple):
            env['SERVER_NAME'] = self._protocol.server_name or sockname[0]
            env['SERVER_PORT'] = str(sockname[1])
        else:
            env['SERVER_NAME'] = self._protocol.server_name or sockname
            env['SERVER_PORT'] = ''
        env['SERVER_SOFTWARE'] = self._protocol.identifier
        env['SERVER_PROTOCOL'] = 'HTTP/{0}'.format(m.version)
        env['REQUEST_METHOD'] = m.method
        env['PATH_INFO'] = m.parsed_url[3]
        env['QUERY_STRING'] = m.parsed_url[4]
        for field, value in m.headers:
            if field.title() == 'Content-Length':
                env['CONTENT_LENGTH'] = value
            elif field.title() == 'Content-Type':
                env['CONTENT_TYPE'] = value
            else:
                env['HTTP_{0}'.format(field.upper().replace('-', '_'))] = value
        env['REQUEST_URI'] = m.url
        # Support the de-facto X-Forwarded-For and X-Forwarded-Proto headers
        # that are added by reverse proxies.
        remote = env.get('HTTP_X_FORWARDED_FOR')
        peername = self._transport.get_extra_info('peername')
        env['REMOTE_ADDR'] = remote if remote else peername[0] \
                                        if isinstance(peername, tuple) else ''
        # SSL information
        sslinfo = self._transport.get_extra_info('sslinfo')
        cipherinfo = sslinfo.cipher() if sslinfo else None
        if sslinfo and cipherinfo:
            env['HTTPS'] = '1'
            env['SSL_CIPHER'] = cipherinfo[0]
            env['SSL_PROTOCOL'] = cipherinfo[1]
            env['SSL_CIPHER_USEKEYSIZE'] = int(cipherinfo[2])
        # WSGI specific variables
        env['wsgi.version'] = (1, 0)
        env['wsgi.errors'] = ErrorStream(self._log)
        env['wsgi.multithread'] = True
        env['wsgi.multiprocess'] = True
        env['wsgi.run_once'] = False
        env['wsgi.input'] = m.body
        proto = env.get('HTTP_X_FORWARDED_PROTO')
        env['wsgi.url_scheme'] = proto if proto else 'https' \
                                        if env.get('HTTPS') else 'http'
        env['REQUEST_SCHEME'] = env['wsgi.url_scheme']
        # Gruvi specific variables
        env['gruvi.version'] = version_info['version']
        env['gruvi.transport'] = self._transport
        env['gruvi.protocol'] = self._protocol


class HttpProtocol(MessageProtocol):
    """HTTP protocol."""

    identifier = '{0[name]}/{0[version]}'.format(version_info)

    def __init__(self, server_side, application=None, server_name=None, version='1.1',
                 timeout=None):
        """
        The *server_side* argument specifies whether this is a client or server
        side protocol.

        If this is a server side protocol, then the *wsgi_application* argument
        must be provided, and it must be a WSGI application callable.

        The *server_name* argument can be used to override the server name for
        server side protocols. If not provided, then the socket name of the
        listening socket will be used.
        """
        if server_side and not application:
            raise ValueError('application is required for server-side protocol')
        message_handler = WsgiHandler(application) if server_side else None
        super(HttpProtocol, self).__init__(message_handler)
        self._server_side = server_side
        self._server_name = server_name
        if version not in ('1.0', '1.1'):
            raise ValueError('version: unsupported version {0!s}'.format(version))
        self._version = version
        self._timeout = timeout
        self._create_parser()
        self._requests = []
        self._header_size = 0
        self._all_body_sizes = 0
        if server_side:
            target = getattr(application, '__qualname__', application.__name__)
            self._log.debug('using wsgi handler {}', target)
        self._response = None

    @property
    def server_side(self):
        """Return whether the protocol is server-side."""
        return self._server_side

    @property
    def server_name(self):
        """Return the server name."""
        return self._server_name

    def _create_parser(self):
        # Create a new CFFI http-parser and settings object that is hooked to
        # our callbacks.
        self._parser = _ffi.new('http_parser *')
        kind = _lib.HTTP_REQUEST if self._server_side else _lib.HTTP_RESPONSE
        _lib.http_parser_init(self._parser, kind)
        settings = _ffi.new('http_parser_settings *')
        refs = {}  # prevent garbage collection of cffi callbacks
        names = [name for name in dir(self) if name.startswith('on_')]
        for name in names:
            cbtype = 'http_cb' if 'complete' in name or 'begin' in name else 'http_data_cb'
            cb = refs[name] = _ffi.callback(cbtype, getattr(self, name))
            setattr(settings, name, cb)
        self._settings = settings
        self._callback_refs = refs

    def _update_header_size(self, length):
        # Add *length* to the size of the current HTTP header. If the size
        # becomes larger than the high-water mark then set an error. This is
        # needed because we cannot consume any of the read buffer until we've
        # got a full header and we can dispatch the message.
        self._header_size += length
        if self._header_size >= self._read_buffer_high:
            self._error = HttpError('HTTP header too large')
            return False
        self.read_buffer_size_changed()
        return True

    def _update_body_size(self, reader, oldsize, newsize):
        # Installed as the "on_buffer_size_changed" callback to the Reader
        # instances of all requests in the queue.
        self._all_body_sizes += (newsize - oldsize)

    def get_read_buffer_size(self):
        return self._header_size + self._queue.qsize() + self._all_body_sizes

    def on_message_begin(self, parser):
        # http-parser callback: prepare for a new message
        self._url = bytearray()
        self._field_name = bytearray()
        self._field_value = bytearray()
        assert self._header_size == 0
        self._message = HttpMessage()
        return 0

    def on_url(self, parser, at, length):
        # http-parser callback: got a piece of the URL
        if not self._update_header_size(length):
            return 1
        self._url.extend(_ffi.buffer(at, length))
        return 0

    def _complete_header_field(self, buf):
        # Add a chunk to a header field. May need to store away a previous
        # (field, value) pair.
        if self._field_value:
            # Store previous field_name, field_value pair
            if not self._message.body:
                self._message.headers.append((_ba2s(self._field_name),
                                              _ba2s(self._field_value)))
            else:
                self._message.trailers.append((_ba2s(self._field_name),
                                               _ba2s(self._field_value)))
            del self._field_name[:]
            del self._field_value[:]
        self._field_name.extend(buf)

    def _complete_header_value(self, buf):
        # Add a chunk to a header value. If buf == b'', then complete any
        # (field, value) pair that is in progress.
        if buf:
            self._field_value.extend(buf)
        elif self._field_name:
            if not self._message.body:
                self._message.headers.append((_ba2s(self._field_name),
                                              _ba2s(self._field_value)))
            else:
                self._message.trailers.append((_ba2s(self._field_name),
                                               _ba2s(self._field_value)))
            del self._field_name[:]
            del self._field_value[:]

    def on_header_field(self, parser, at, length):
        # http-parser callback: got a piece of a header name
        if not self._update_header_size(length):
            return 1
        buf = _ffi.buffer(at, length)
        self._complete_header_field(buf)
        return 0

    def on_header_value(self, parser, at, length):
        # http-parser callback: got a piece of a header value
        if not self._update_header_size(length):
            return 1
        buf = _ffi.buffer(at, length)
        self._complete_header_value(buf)
        return 0

    def on_headers_complete(self, parser):
        # http-parser callback: the HTTP header is complete. This is the point
        # where we hand off the message to our consumer. Going forward,
        # on_body() will continue to write chunks of the body to message.body.
        self._complete_header_value(b'')
        m = self._message
        m.message_type = _lib.http_message_type(parser)
        m.version = '{0}.{1}'.format(parser.http_major, parser.http_minor)
        if self._server_side:
            m.method = _cd2s(_lib.http_method_str(parser.method))
            m.url = _ba2s(self._url)
            try:
                m.parsed_url = parse_url(self._url)
            except ValueError as e:
                self._error = HttpError('urlsplit(): {0!s}'.format(e))
                return 2  # error
            m.is_upgrade = _lib.http_is_upgrade(parser)
        else:
            m.status_code = parser.status_code
        m.should_keep_alive = _lib.http_should_keep_alive(parser)
        m.body = StreamReader(self._update_body_size)
        # Make the message available. There is no need to call
        # read_buffer_size_change() here as the changes sum up to 0.
        self._queue.put_nowait(m, self._header_size)
        self._header_size = 0
        # Return 1 if this is a HEAD request, 0 otherwise. This instructs the
        # parser whether or not a body follows.
        if not self._requests:
            return 0
        return 1 if self._requests.pop(0) == 'HEAD' else 0

    def on_body(self, parser, at, length):
        # http-parser callback: got a body chunk
        self._message.body.feed(bytes(_ffi.buffer(at, length)))
        return 0

    def on_message_complete(self, parser):
        # http-parser callback: the body ended
        # complete any trailers that might be present
        self._complete_header_value(b'')
        self._message.body.feed_eof()
        return 0

    def data_received(self, data):
        # Protocol callback
        nbytes = _lib.http_parser_execute(self._parser, self._settings, data, len(data))
        if nbytes != len(data):
            msg = _cd2s(_lib.http_errno_name(_lib.http_errno(self._parser)))
            self._log.debug('http_parser_execute(): {0}'.format(msg))
            self._error = HttpError('parse error: {0}'.format(msg))
            self._transport.close()

    def connection_lost(self, exc):
        # Protocol callback
        # Feed the EOF to the parser. It will tell us it if was unexpected.
        nbytes = _lib.http_parser_execute(self._parser, self._settings, b'', 0)
        if nbytes != 0:
            msg = _cd2s(_lib.http_errno_name(_lib.http_errno(self._parser)))
            self._log.debug('http_parser_execute(): {0}'.format(msg))
            if exc is None:
                exc = HttpError('parse error: {0}'.format(msg))
        super(HttpProtocol, self).connection_lost(exc)

    @switchpoint
    def request(self, method, url, headers=[], body=b''):
        """Make a new HTTP request.

        The *method* argument is the HTTP method to be used. It must be
        specified as a string, for example ``'GET'`` or ``'POST'``. The *url*
        argument specifies the URL and must be a string as well.

        The optional *headers* argument specifies extra HTTP headers to use in
        the request. It must be a list of (name, value) tuples, with name and
        value a string.

        The optional *body* argument may be used to specify a body to include
        in the request. It must be a ``bytes`` or ``str`` instance, a file-like
        object, or an iterable producing ``bytes`` or ``str`` instances. The
        default value for the body is the empty string ``b''`` which sends an
        empty body. To send potentially very large bodies, use the file or
        iterator interface. Using these interfaces will send the body under the
        "chunked" transfer encoding. This has the added advantage that the body
        size does not need to be known up front.

        The body may also be the ``None``, which means that you need to send
        the request body yourself. This is explained below.

        This method sends the request header, and if a body was specified, the
        request body as well. It then returns a :class:`HttpRequest` instance.

        If however you passsed a *body* of ``None`` then you must use the
        :meth:`HttpRequest.write` and :meth:`HttpRequest.end_request` methods
        if the :class:`HttpRequest` instance to send the request body yourself.
        This functionality is only useful if you want to sent trailers with the
        HTTP "chunked" encoding. Trailers are not normally used.

        The response to the request can be obtained by calling the
        :meth:`get_response` method.

        You may make multiple requests before reading a response. This is
        called pipelining, and can improve per request latency greatly. For
        every request that you make, you must call :meth:`get-response` exactly
        once. The remote HTTP implementation will send by the responses in the
        same order as the requests.
        """
        if self._error:
            raise self._error
        elif self._closing or self._closed:
            raise HttpError('protocol is closing/closed')
        self._requests.append(method)
        request = HttpRequest(self._transport, self)
        request.start_request(method, url, headers, body)
        if body is None:
            return request
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
    def get_response(self, timeout=-1):
        """Wait for and return a HTTP response.

        The return value is a :class:`HttpResponse` instance. When this method
        returns, only the response header has been read. The response body can
        be read using the :meth:`HttpResponse.read` and similar methods.

        Note that it is requires  that you read the entire body of each
        response if you use HTTP pipelining. Specifically, it is an error to
        call :meth:`get_response` when the body of the response returned by a
        previous invocation has not yet been fully read.
        """
        if self._error:
            raise self._error
        elif self._closed:
            raise HttpError('protocol is closed')
        if not self._requests and not self._queue.qsize():
            raise RuntimeError('there are no outstanding requests')
        if timeout < 0:
            timeout = self._timeout
        if self._response and not self._response.body.eof:
            raise RuntimeError('body of previous response not completely read')
        message = self._queue.get(timeout=timeout)
        self._response = message
        return HttpResponse(message)


class HttpClient(Client):
    """A HTTP client."""

    def __init__(self, timeout=None):
        """The optional *timeout* argument can be used to specify a timeout for
        the various network operations used within the client."""
        super(HttpClient, self).__init__(self._create_protocol, timeout=timeout)
        self._server_name = None

    @docfrom(Client.connect)
    def connect(self, address, **kwargs):
        # Capture the host name that we are connecting to. We need this for
        # generating "Host" headers in HTTP/1.1
        if isinstance(address, tuple):
            host, port = address[:2]  # len(address) == 4 for IPv6
            default_port = (port == HTTP_PORT and 'ssl' not in kwargs) \
                                or (port == HTTPS_PORT and 'ssl' in kwargs)
            if not default_port:
                host = '{0}:{1}'.format(host, port)
            self._server_name = host
        return super(HttpClient, self).connect(address, **kwargs)

    add_protocol_method(HttpProtocol.request, globals(), locals())
    add_protocol_method(HttpProtocol.get_response, globals(), locals())

    def _create_protocol(self):
        return HttpProtocol(False, server_name=self._server_name, timeout=self._timeout)


class HttpServer(Server):
    """A HTTP server."""

    def __init__(self, application, server_name=None, timeout=None):
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
        super(HttpServer, self).__init__(self._create_protocol, timeout)
        self._application = application
        self._server_name = server_name

    def _create_protocol(self):
        return HttpProtocol(True, self._application, server_name=self._server_name,
                            timeout=self._timeout)
