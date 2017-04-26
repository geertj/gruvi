#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import unittest

from gruvi import http
from gruvi.http import HttpServer, HttpClient, HttpMessage, HttpProtocol, ParsedUrl
from gruvi.http import parse_content_type, parse_te, parse_trailer, parse_url
from gruvi.http import get_header, remove_headers
from gruvi.stream import Stream, StreamClient
from gruvi.sync import Queue

from support import UnitTest, MockTransport

URL = ParsedUrl


class TestParseContentType(UnitTest):

    def test_simple(self):
        parsed = parse_content_type('text/plain')
        self.assertEqual(parsed, ('text/plain', {}))

    def test_params(self):
        parsed = parse_content_type('text/plain; charset=foo')
        self.assertEqual(parsed[0], 'text/plain')
        self.assertEqual(parsed[1], {'charset': 'foo'})

    def test_iso8859_1(self):
        parsed = parse_content_type('text/plain; foo="bar\xfe"')
        self.assertEqual(parsed, ('text/plain', {'foo': 'bar\xfe'}))

    def test_param_whitespace(self):
        parsed = parse_content_type('text/plain;   charset=foo    ')
        self.assertEqual(parsed, ('text/plain', {'charset': 'foo'}))

    def test_param_quoted(self):
        parsed = parse_content_type('text/plain; charset="foo bar"')
        self.assertEqual(parsed, ('text/plain', {'charset': 'foo bar'}))

    def test_param_quoted_pair(self):
        parsed = parse_content_type('text/plain; charset="foo\\"bar"')
        self.assertEqual(parsed, ('text/plain', {'charset': 'foo"bar'}))

    def test_param_empty(self):
        parsed = parse_content_type('text/plain; charset=""')
        self.assertEqual(parsed, ('text/plain', {'charset': ''}))

    def test_param_multiple(self):
        parsed = parse_content_type('text/plain; foo=bar; baz=qux')
        self.assertEqual(parsed, ('text/plain', {'foo': 'bar', 'baz': 'qux'}))

    def test_param_multiple_missing_semi(self):
        parsed = parse_content_type('text/plain; foo=bar baz=qux')
        self.assertEqual(parsed, ('text/plain', {'foo': 'bar'}))


class TestParseTE(UnitTest):

    def test_simple(self):
        parsed = parse_te('chunked')
        self.assertEqual(parsed, [('chunked', None)])

    def test_multiple(self):
        parsed = parse_te('chunked, deflate')
        self.assertEqual(parsed, [('chunked', None), ('deflate', None)])

    def test_qvalue(self):
        parsed = parse_te('deflate; q=0.5')
        self.assertEqual(parsed, [('deflate', '0.5')])

    def test_case_insensitive(self):
        parsed = parse_te('dEfLaTe; Q=0.5')
        self.assertEqual(parsed, [('dEfLaTe', '0.5')])

    def test_illegal_qvalue(self):
        parsed = parse_te('deflate; q=2.5')
        self.assertEqual(parsed, [('deflate', None)])

    def test_multiple_qvalue(self):
        parsed = parse_te('deflate; q=0.5, zlib; q=0.8')
        self.assertEqual(parsed, [('deflate', '0.5'), ('zlib', '0.8')])


class TestParseTrailer(UnitTest):

    def test_simple(self):
        parsed = parse_trailer('foo')
        self.assertEqual(parsed, ['foo'])

    def test_multiple(self):
        parsed = parse_trailer('foo, bar')
        self.assertEqual(parsed, ['foo', 'bar'])

    def test_spacing(self):
        parsed = parse_trailer('foo   , bar   ')
        self.assertEqual(parsed, ['foo', 'bar'])

    def test_wrong_separator(self):
        parsed = parse_trailer('foo; bar')
        self.assertEqual(parsed, ['foo'])


class TestParseUrl(UnitTest):

    def test_test(self):
        self.assertEqual(URL(), ('', '', '', '', '', '', ''))
        self.assertEqual(URL(scheme='http'), ('http', '', '', '', '', '', ''))
        self.assertEqual(URL(host='foo'), ('', 'foo', '', '', '', '', ''))
        self.assertEqual(URL(path='/path'), ('', '', '/path', '', '', '', ''))
        self.assertEqual(URL(query='foo=bar'), ('', '', '', 'foo=bar', '', '', ''))
        self.assertEqual(URL(fragment='baz'), ('', '', '', '', 'baz', '', ''))
        self.assertEqual(URL(port='80'), ('', '', '', '', '', '80', ''))
        self.assertEqual(URL(userinfo='user:pass'), ('', '', '', '', '', '', 'user:pass'))

    def test_origin(self):
        parsed = parse_url('/path')
        self.assertEqual(parsed, URL(path='/path'))

    def test_absolute(self):
        parsed = parse_url('http://example.com/path')
        self.assertEqual(parsed, URL('http', 'example.com', '/path'))

    def test_authority(self):
        parsed = parse_url('example.com:80', is_connect=True)
        self.assertEqual(parsed, URL('', 'example.com', port='80'))

    def test_authority_error(self):
        self.assertRaises(ValueError, parse_url, '/path', is_connect=True)
        self.assertRaises(ValueError, parse_url, 'http://example.com:80', is_connect=True)
        self.assertRaises(ValueError, parse_url, '*', is_connect=True)

    def test_asterisk(self):
        parsed = parse_url('*')
        self.assertEqual(parsed, URL(path='*'))

    def test_userinfo(self):
        parsed = parse_url('http://user:pass@example.com')
        self.assertEqual(parsed, URL('http', 'example.com', userinfo='user:pass'))

    def test_port(self):
        parsed = parse_url('http://example.com:80')
        self.assertEqual(parsed, URL('http', 'example.com', port='80'))

    def test_userinfo_port(self):
        parsed = parse_url('http://user:pass@example.com:80')
        self.assertEqual(parsed, URL('http', 'example.com', port='80', userinfo='user:pass'))

    def test_default_scheme(self):
        parsed = parse_url('www.example.com')
        self.assertEqual(parsed, URL('http', 'www.example.com'))
        parsed = parse_url('http://www.example.com')
        self.assertEqual(parsed, URL('http', 'www.example.com'))
        parsed = parse_url('www.example.com', default_scheme='https')
        self.assertEqual(parsed, URL('https', 'www.example.com'))
        parsed = parse_url('https://www.example.com', default_scheme='https')
        self.assertEqual(parsed, URL('https', 'www.example.com'))

    def test_addr(self):
        parsed = parse_url('www.example.com')
        self.assertEqual(parsed.addr, ('www.example.com', 80))
        parsed = parse_url('https://www.example.com')
        self.assertEqual(parsed.addr, ('www.example.com', 443))

    def test_ssl(self):
        parsed = parse_url('www.example.com')
        self.assertFalse(parsed.ssl)
        parsed = parse_url('http://www.example.com')
        self.assertFalse(parsed.ssl)
        parsed = parse_url('https://www.example.com')
        self.assertTrue(parsed.ssl)

    def test_target(self):
        parsed = parse_url('www.example.com')
        self.assertEqual(parsed.target, '/')
        parsed = parse_url('www.example.com/foo')
        self.assertEqual(parsed.target, '/foo')
        parsed = parse_url('www.example.com?bar')
        self.assertEqual(parsed.target, '/?bar')
        parsed = parse_url('www.example.com/foo?bar')
        self.assertEqual(parsed.target, '/foo?bar')


class TestGetHeader(UnitTest):

    headers = [('foo', 'fooval'),
               ('bar', 'barval'),
               ('baz', 'bazval')]

    def test_simple(self):
        self.assertEqual(get_header(self.headers, 'foo'), 'fooval')
        self.assertEqual(get_header(self.headers, 'bar'), 'barval')
        self.assertEqual(get_header(self.headers, 'baz'), 'bazval')

    def test_case_insensitive(self):
        self.assertEqual(get_header(self.headers, 'Foo'), 'fooval')
        self.assertEqual(get_header(self.headers, 'FOO'), 'fooval')

    def test_not_present(self):
        self.assertIsNone(get_header(self.headers, 'qux'))

    def test_default_value(self):
        self.assertEqual(get_header(self.headers, 'qux', 'quxval'), 'quxval')


class TestRemoveHeaders(UnitTest):

    headers = [('foo', 'fooval1'),
               ('bar', 'barval1'),
               ('foo', 'fooval2'),
               ('baz', 'bazval'),
               ('bar', 'barval2')]

    def test_simple(self):
        self.assertEqual(remove_headers(self.headers[:], 'foo'),
                         [('bar', 'barval1'), ('baz', 'bazval'), ('bar', 'barval2')])
        self.assertEqual(remove_headers(self.headers[:], 'bar'),
                         [('foo', 'fooval1'), ('foo', 'fooval2'), ('baz', 'bazval')])

    def test_in_place(self):
        headers = self.headers[:]
        removed = remove_headers(headers, 'foo')
        self.assertIs(headers, removed)

    def test_non_quadratic(self):
        # Ensure remove_headers() doesn't take quadratic time.
        names = ('foo', 'bar', 'baz', 'qux')
        headers = []
        for i in range(100000):
            name = names[i%4]
            headers.append((name, name + 'val'))
        removed = remove_headers(headers, 'foo')
        self.assertEqual(len(removed), 75000)


class TestHttpProtocol(UnitTest):

    def setUp(self):
        super(TestHttpProtocol, self).setUp()
        self.requests = Queue()

    def store_request(self, message, transport, protocol):
        self.requests.put(message)
        protocol.writer.write(b'HTTP/1.1 200 OK\r\n\r\n')

    def parse_request(self, *chunks):
        # Parse the HTTP request made up of *chunks.
        transport = MockTransport()
        protocol = HttpProtocol(self.store_request, server_side=True)
        transport.start(protocol)
        for chunk in chunks:
            protocol.data_received(chunk)
        self.assertIsNone(protocol._error)
        self.transport = transport
        self.protocol = protocol

    def get_request(self):
        # Get a parsed request.
        m = self.requests.get(timeout=1.0)
        self.assertIsInstance(m, HttpMessage)
        self.assertEqual(m.message_type, http.REQUEST)
        return m

    # Tests that parse a request

    def test_simple_request(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n\r\n'
        self.parse_request(r)
        m = self.get_request()
        self.assertEqual(m.version, '1.1')
        self.assertIsNone(m.status_code)
        self.assertEqual(m.method, 'GET')
        self.assertEqual(m.url, '/')
        self.assertTrue(m._should_keep_alive)
        self.assertEqual(m.parsed_url, URL(path='/'))
        self.assertEqual(m.headers, [('Host', 'example.com')])
        self.assertIsInstance(m.body, Stream)
        self.assertTrue(m.body.buffer.eof)

    def test_request_with_body(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 3\r\n\r\nFoo'
        self.parse_request(r)
        m = self.get_request()
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'), ('Content-Length', '3')])
        self.assertFalse(m.body.buffer.eof)
        self.assertEqual(m.body.read(), b'Foo')
        self.assertTrue(m.body.buffer.eof)

    def test_request_with_body_incremental(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 3\r\n\r\nFoo'
        self.parse_request(*[r[i:i+1] for i in range(len(r))])
        m = self.get_request()
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'), ('Content-Length', '3')])
        self.assertFalse(m.body.buffer.eof)
        self.assertEqual(m.body.read(), b'Foo')
        self.assertTrue(m.body.buffer.eof)

    def test_request_with_chunked_body(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Transfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_request(r)
        m = self.get_request()
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'),
                                     ('Transfer-Encoding', 'chunked')])
        self.assertFalse(m.body.buffer.eof)
        self.assertEqual(m.body.read(), b'Foo')
        self.assertTrue(m.body.buffer.eof)

    def test_request_with_chunked_body_incremental(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Transfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_request(*[r[i:i+1] for i in range(len(r))])
        m = self.get_request()
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'),
                                     ('Transfer-Encoding', 'chunked')])
        self.assertFalse(m.body.buffer.eof)
        self.assertEqual(m.body.read(), b'Foo')
        self.assertTrue(m.body.buffer.eof)

    def test_request_with_chunked_body_and_trailers(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Transfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\nETag: foo\r\n\r\n'
        self.parse_request(r)
        m = self.get_request()
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'),
                                     ('Transfer-Encoding', 'chunked'),
                                     ('ETag', 'foo')])
        self.assertFalse(m.body.buffer.eof)
        self.assertEqual(m.body.read(), b'Foo')
        self.assertTrue(m.body.buffer.eof)

    def test_pipelined_requests(self):
        r = b'GET /0 HTTP/1.1\r\nHost: example0.com\r\n\r\n' \
            b'GET /1 HTTP/1.1\r\nHost: example1.com\r\n\r\n'
        self.parse_request(r)
        for i in range(2):
            m = self.get_request()
            self.assertEqual(m.url, '/{0}'.format(i))
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.headers, [('Host', 'example{}.com'.format(i))])
            self.assertTrue(m.body.buffer.eof)

    def test_pipelined_requests_with_body(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 4\r\n\r\nFoo0' \
            b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 4\r\n\r\nFoo1'
        self.parse_request(r)
        for i in range(2):
            m = self.get_request()
            self.assertEqual(m.url, '/')
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.headers, [('Host', 'example.com'), ('Content-Length', '4')])
            self.assertFalse(m.body.buffer.eof)
            self.assertEqual(m.body.read(), 'Foo{}'.format(i).encode('ascii'))
            self.assertTrue(m.body.buffer.eof)

    def test_request_url(self):
        r = b'GET /foo/bar HTTP/1.1\r\n' \
            b'Host: example.com\r\n\r\n'
        self.parse_request(r)
        m = self.get_request()
        self.assertEqual(m.parsed_url, URL(path='/foo/bar'))

    def test_long_request_url(self):
        r = b'GET http://user:pass@example.com:80/foo/bar?baz=qux#quux HTTP/1.1\r\n' \
            b'Host: example.com\r\n\r\n'
        self.parse_request(r)
        m = self.get_request()
        self.assertEqual(m.parsed_url, URL('http', 'example.com', '/foo/bar', 'baz=qux', 'quux',
                                           port='80', userinfo='user:pass'))

    # Tests that parse a response

    def parse_response(self, *chunks, **kwargs):
        # Parse the HTTP resposne made up of *chunks.
        transport = MockTransport()
        protocol = HttpProtocol()
        transport.start(protocol)
        methods = kwargs.get('methods', [])
        if methods:
            protocol._requests = methods
        for chunk in chunks:
            protocol.data_received(chunk)
        self.assertIsNone(protocol._error)
        self.transport = transport
        self.protocol = protocol

    def get_response(self):
        # Get a parsed resposne.
        m = self.protocol.getresponse()
        self.assertIsInstance(m, HttpMessage)
        self.assertEqual(m.message_type, http.RESPONSE)
        return m

    def test_simple_response(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n'
        self.parse_response(r)
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.headers, [('Content-Length', '0')])
        self.assertEqual(m.get_header('Content-Length'), '0')
        self.assertEqual(m.body.read(), b'')
        self.assertTrue(m.body.buffer.eof)

    def test_response_with_body(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nFoo'
        self.parse_response(r)
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.headers, [('Content-Length', '3')])
        self.assertEqual(m.get_header('Content-Length'), '3')
        self.assertEqual(m.body.read(), b'Foo')
        self.assertEqual(m.body.read(), b'')

    def test_response_with_body_incremental(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nFoo'
        self.parse_response([r[i:i+1] for i in range(len(r))])
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.headers, [('Content-Length', '3')])
        self.assertEqual(m.body.read(), b'Foo')
        self.assertEqual(m.body.read(), b'')

    def test_response_with_chunked_body(self):
        r = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_response(r)
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.headers, [('Transfer-Encoding', 'chunked')])
        self.assertEqual(m.body.read(), b'Foo')
        self.assertEqual(m.body.read(), b'')

    def test_response_with_chunked_body_incremental(self):
        r = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_response([r[i:i+1] for i in range(len(r))])
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.headers, [('Transfer-Encoding', 'chunked')])
        self.assertEqual(m.body.read(), b'Foo')
        self.assertEqual(m.body.read(), b'')

    def test_response_with_chunked_body_and_trailers(self):
        r = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\nETag: foo\r\n\r\n'
        self.parse_response(r)
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.headers, [('Transfer-Encoding', 'chunked'), ('ETag', 'foo')])
        self.assertEqual(m.body.read(), b'Foo')
        self.assertEqual(m.body.read(), b'')

    def test_pipelined_responses(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nSet-Cookie: foo=0\r\n\r\n' \
            b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nSet-Cookie: foo=1\r\n\r\n'
        self.parse_response(r)
        for i in range(2):
            m = self.get_response()
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.status_code, 200)
            cookie = 'foo={0}'.format(i)
            self.assertEqual(m.headers, [('Content-Length', '0'), ('Set-Cookie', cookie)])
            self.assertEqual(m.body.read(), b'')

    def test_pipelined_responses_with_body(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nFoo0' \
            b'HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nFoo1'
        self.parse_response(r)
        for i in range(2):
            m = self.get_response()
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.status_code, 200)
            self.assertEqual(m.headers, [('Content-Length', '4')])
            self.assertEqual(m.body.read(), 'Foo{0}'.format(i).encode('ascii'))
            self.assertEqual(m.body.read(), b'')

    def test_pipelined_head_responses(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n' \
            b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n'
        self.parse_response(r, methods=['HEAD', 'HEAD'])
        for i in range(2):
            m = self.get_response()
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.status_code, 200)
            self.assertEqual(m.headers, [('Content-Length', '3')])
            self.assertEqual(m.body.read(), b'')

    def test_pipelined_empty_responses(self):
        # These status codes take no body. The parser should know this.
        r = b'HTTP/1.1 100 OK\r\nCookie: foo0\r\n\r\n' \
            b'HTTP/1.1 204 OK\r\nCookie: foo1\r\n\r\n' \
            b'HTTP/1.1 304 OK\r\nCookie: foo2\r\n\r\n'
        self.parse_response(r)
        for i in range(3):
            m = self.get_response()
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.headers, [('Cookie', 'foo{0}'.format(i))])
            self.assertEqual(m.body.read(), b'')

    def test_pipelined_200_response_eof(self):
        # No content-length so 200 requires and EOF to indicate the end of
        # message. The second request is therefore interpreted as a the body of
        # the first.
        r = b'HTTP/1.1 200 OK\r\nCookie: foo0\r\n\r\nfoo'
        self.parse_response(r)
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Cookie', 'foo0')])
        self.assertEqual(m.body.read(3), b'foo')
        self.assertFalse(m.body.buffer.eof)
        self.protocol.connection_lost(None)
        self.assertTrue(m.body.buffer.eof)
        self.assertEqual(m.body.read(), b'')

    def test_pipelined_204_response_eof(self):
        # A 204 never has a body so the absence of a Content-Length header
        # still does not require it to see an EOF.
        r = b'HTTP/1.1 204 OK\r\nCookie: foo0\r\n\r\n'
        self.parse_response(r)
        m = self.get_response()
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Cookie', 'foo0')])
        self.assertEqual(m.body.read(), b'')


def hello_app(environ, start_response):
    headers = [('Content-Type', 'text/plain')]
    start_response('200 OK', headers)
    return [b'Hello!']


def echo_app(environ, start_response):
    headers = [('Content-Type', 'text/plain')]
    for name in environ:
        if name.startswith('HTTP_X'):
            hname = name[5:].replace('_', '-').title()
            headers.append((hname, environ[name]))
    headers.sort()  # for easier comparison
    body = environ['wsgi.input'].read()
    start_response('200 OK', headers)
    return [body]


class TestHttp(UnitTest):

    def test_simple(self):
        server = HttpServer(hello_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('GET', '/')
        resp = client.getresponse()
        self.assertEqual(resp.version, '1.1')
        self.assertEqual(resp.status_code, 200)
        serv = resp.get_header('Server')
        self.assertTrue(serv.startswith('gruvi'))
        ctype = resp.get_header('Content-Type')
        self.assertEqual(ctype, 'text/plain')
        self.assertEqual(resp.body.read(), b'Hello!')
        server.close()
        client.close()

    def test_simple_pipe(self):
        server = HttpServer(hello_app)
        server.listen(self.pipename())
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('GET', '/')
        resp = client.getresponse()
        self.assertEqual(resp.body.read(), b'Hello!')
        server.close()
        client.close()

    def test_simple_ssl(self):
        server = HttpServer(hello_app)
        context = self.get_ssl_context()
        server.listen(('localhost', 0), ssl=context)
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr, ssl=context)
        client.request('GET', '/')
        resp = client.getresponse()
        self.assertEqual(resp.body.read(), b'Hello!')
        server.close()
        client.close()

    def test_request_headers(self):
        server = HttpServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('GET', '/', headers=[('X-Echo', 'Bar')])
        resp = client.getresponse()
        self.assertEqual(resp.get_header('X-Echo'), 'Bar')
        body = resp.body.read()
        self.assertEqual(body, b'')
        server.close()
        client.close()

    def test_request_body(self):
        server = HttpServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('POST', '/', body=b'foo')
        resp = client.getresponse()
        body = resp.body.read()
        self.assertEqual(body, b'foo')
        server.close()
        client.close()

    def test_request_body_sequence(self):
        server = HttpServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('POST', '/', body=[b'foo', b'bar'])
        resp = client.getresponse()
        body = resp.body.read()
        self.assertEqual(body, b'foobar')
        server.close()
        client.close()

    def test_request_trailers(self):
        server = HttpServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        headers = [('X-Echo', 'Bar'), ('Trailer', 'X-Length')]
        def genbody():
            yield b'FooBody'
            headers.append(('X-Length', '7'))
        client.request('GET', '/', body=genbody(), headers=headers)
        resp = client.getresponse()
        self.assertEqual(resp.get_header('X-Echo'), 'Bar')
        self.assertEqual(resp.get_header('X-Length'), '7')
        body = resp.body.read()
        self.assertEqual(body, b'FooBody')
        server.close()
        client.close()

    def test_illegal_request(self):
        server = HttpServer(hello_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = StreamClient()
        client.connect(addr)
        client.write(b'foo\r\n')
        client.write_eof()
        buf = client.read()
        self.assertEqual(buf, b'')
        server.close()
        client.close()


if __name__ == '__main__':
    unittest.main()
