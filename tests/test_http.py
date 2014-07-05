#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import six

import gruvi
from gruvi.http import HttpServer, HttpClient
from gruvi.http import HttpMessage, HttpProtocol, HttpResponse
from gruvi.http import parse_option_header
from gruvi.http_ffi import lib as _lib
from gruvi.stream import StreamReader

from support import UnitTest, unittest, MockTransport


class TestSplitOptionHeader(UnitTest):

    def test_basic(self):
        parsed = parse_option_header('text/plain; charset=foo')
        self.assertIsInstance(parsed, tuple)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0], 'text/plain')
        self.assertEqual(parsed[1], {'charset': 'foo'})

    def test_plain(self):
        parsed = parse_option_header('text/plain')
        self.assertEqual(parsed, ('text/plain', {}))

    def test_iso8859_1(self):
        parsed = parse_option_header('text/plain; foo="bar\xfe"')
        self.assertEqual(parsed, ('text/plain', {'foo': 'bar\xfe'}))

    def test_whitespace(self):
        parsed = parse_option_header('text/plain;   charset=foo    ')
        self.assertEqual(parsed, ('text/plain', {'charset': 'foo'}))

    def test_quoted(self):
        parsed = parse_option_header('text/plain; charset="foo bar"')
        self.assertEqual(parsed, ('text/plain', {'charset': 'foo bar'}))

    def test_multiple(self):
        parsed = parse_option_header('text/plain; foo=bar baz=qux')
        self.assertEqual(parsed, ('text/plain', {'foo': 'bar', 'baz': 'qux'}))

    def test_empty(self):
        parsed = parse_option_header('text/plain; charset=""')
        self.assertEqual(parsed, ('text/plain', {'charset': ''}))


class TestHttpProtocol(UnitTest):

    def setUp(self):
        super(TestHttpProtocol, self).setUp()
        self.environs = []

    def store_request(self, environ, start_response):
        environ['test.message'] = start_response.__self__._message
        environ['test.body'] = environ['wsgi.input'].read()
        self.environs.append(environ.copy())
        start_response('200 OK', [])
        return b''

    def parse_request(self, *chunks):
        # Parse the HTTP request made up of *chunks.
        transport = MockTransport()
        protocol = HttpProtocol(True, self.store_request)
        transport.start(protocol)
        for chunk in chunks:
            protocol.data_received(chunk)
        self.assertIsNone(protocol._error)
        self.transport = transport
        self.protocol = protocol

    def get_request(self):
        # Get a parsed request.
        # The sleep here will run the dispatcher.
        gruvi.sleep(0)
        self.assertGreaterEqual(len(self.environs), 1)
        env = self.environs.pop(0)
        self.assertIsInstance(env, dict)
        message = env.get('test.message')
        self.assertIsInstance(message, HttpMessage)
        self.assertEqual(message.message_type, _lib.HTTP_REQUEST)
        body = env.get('test.body')
        self.assertIsInstance(body, six.binary_type)
        return env

    # Tests that parse a request

    def test_simple_request(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n\r\n'
        self.parse_request(r)
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.version, '1.1')
        self.assertIsNone(m.status_code)
        self.assertEqual(m.method, 'GET')
        self.assertEqual(m.url, '/')
        self.assertFalse(m.is_upgrade)
        self.assertTrue(m.should_keep_alive)
        self.assertEqual(m.parsed_url, ('', '', '/', '', ''))
        self.assertEqual(m.headers, [('Host', 'example.com')])
        self.assertEqual(m.trailers, [])
        self.assertIsInstance(m.body, StreamReader)
        self.assertTrue(m.body.eof)
        self.assertEqual(env['test.body'], b'')

    def test_request_with_body(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 3\r\n\r\nFoo'
        self.parse_request(r)
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'), ('Content-Length', '3')])
        self.assertTrue(m.body.eof)
        self.assertEqual(env['test.body'], b'Foo')

    def test_request_with_body_incremental(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 3\r\n\r\nFoo'
        self.parse_request([r[i:i+1] for i in range(len(r))])
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'), ('Content-Length', '3')])
        self.assertTrue(m.body.eof)
        self.assertEqual(env['test.body'], b'Foo')

    def test_request_with_chunked_body(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Transfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_request(r)
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'),
                                     ('Transfer-Encoding', 'chunked')])
        self.assertTrue(m.body.eof)
        self.assertEqual(env['test.body'], b'Foo')

    def test_request_with_chunked_body_incremental(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Transfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_request([r[i:i+1] for i in range(len(r))])
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'),
                                     ('Transfer-Encoding', 'chunked')])
        self.assertTrue(m.body.eof)
        self.assertEqual(env['test.body'], b'Foo')

    def test_request_with_chunked_body_and_trailers(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Transfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\nETag: foo\r\n\r\n'
        self.parse_request(r)
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.url, '/')
        self.assertEqual(m.version, '1.1')
        self.assertEqual(m.headers, [('Host', 'example.com'),
                                     ('Transfer-Encoding', 'chunked')])
        self.assertEqual(m.trailers, [('ETag', 'foo')])
        self.assertTrue(m.body.eof)
        self.assertEqual(env['test.body'], b'Foo')

    def test_pipelined_requests(self):
        r = b'GET /0 HTTP/1.1\r\nHost: example0.com\r\n\r\n' \
            b'GET /1 HTTP/1.1\r\nHost: example1.com\r\n\r\n'
        self.parse_request(r)
        for i in range(2):
            env = self.get_request()
            m = env['test.message']
            self.assertEqual(m.url, '/{0}'.format(i))
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.headers, [('Host', 'example{0}.com'.format(i))])
            self.assertTrue(m.body.eof)
            self.assertEqual(env['test.body'], b'')

    def test_pipelined_requests_with_body(self):
        r = b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 4\r\n\r\nFoo0' \
            b'GET / HTTP/1.1\r\nHost: example.com\r\n' \
            b'Content-Length: 4\r\n\r\nFoo1'
        self.parse_request(r)
        for i in range(2):
            env = self.get_request()
            m = env['test.message']
            self.assertEqual(m.url, '/')
            self.assertEqual(m.version, '1.1')
            self.assertEqual(m.headers, [('Host', 'example.com'), ('Content-Length', '4')])
            self.assertEqual(env['test.body'], 'Foo{0}'.format(i).encode('ascii'))

    def test_request_url(self):
        r = b'GET /foo/bar HTTP/1.1\r\n' \
            b'Host: example.com\r\n\r\n'
        self.parse_request(r)
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.parsed_url, ('', '', '/foo/bar', '', ''))

    def test_long_request_url(self):
        r = b'GET http://user:pass@example.com:80/foo/bar?baz=qux#quux HTTP/1.1\r\n' \
            b'Host: example.com\r\n\r\n'
        self.parse_request(r)
        env = self.get_request()
        m = env['test.message']
        self.assertEqual(m.parsed_url, ('http', 'user:pass@example.com:80',
                                        '/foo/bar', 'baz=qux', 'quux'))

    # Tests that parse a response

    def parse_response(self, *chunks, **kwargs):
        # Parse the HTTP resposne made up of *chunks.
        transport = MockTransport()
        protocol = HttpProtocol(False)
        transport.start(protocol)
        methods = kwargs.get('methods', [])
        if methods:
            protocol._requests = methods
        for chunk in chunks:
            protocol.data_received(chunk)
        self.assertIsNone(protocol._error)
        self.transport = transport
        self.protocol = protocol

    def getresponse(self):
        # Get a parsed resposne.
        # The sleep here will run the dispatcher.
        response = self.protocol.getresponse()
        self.assertIsInstance(response, HttpResponse)
        message = response._message
        self.assertIsInstance(message, HttpMessage)
        self.assertEqual(message.message_type, _lib.HTTP_RESPONSE)
        return response

    def test_simple_response(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n'
        self.parse_response(r)
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.status, 200)
        self.assertEqual(ro.headers, [('Content-Length', '0')])
        self.assertEqual(ro.get_header('Content-Length'), '0')
        self.assertEqual(ro.trailers, [])
        self.assertEqual(ro.read(), b'')

    def test_response_with_body(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nFoo'
        self.parse_response(r)
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.status, 200)
        self.assertEqual(ro.headers, [('Content-Length', '3')])
        self.assertEqual(ro.get_header('Content-Length'), '3')
        self.assertEqual(ro.trailers, [])
        self.assertEqual(ro.read(), b'Foo')
        self.assertEqual(ro.read(), b'')

    def test_response_with_body_incremental(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nFoo'
        self.parse_response([r[i:i+1] for i in range(len(r))])
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.status, 200)
        self.assertEqual(ro.headers, [('Content-Length', '3')])
        self.assertEqual(ro.read(), b'Foo')
        self.assertEqual(ro.read(), b'')

    def test_response_with_chunked_body(self):
        r = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_response(r)
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.status, 200)
        self.assertEqual(ro.headers, [('Transfer-Encoding', 'chunked')])
        self.assertEqual(ro.read(), b'Foo')
        self.assertEqual(ro.read(), b'')

    def test_response_with_chunked_body_incremental(self):
        r = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\n\r\n'
        self.parse_response([r[i:i+1] for i in range(len(r))])
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.status, 200)
        self.assertEqual(ro.headers, [('Transfer-Encoding', 'chunked')])
        self.assertEqual(ro.read(), b'Foo')
        self.assertEqual(ro.read(), b'')

    def test_response_with_chunked_body_and_trailers(self):
        r = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' \
            b'3\r\nFoo\r\n0\r\nETag: foo\r\n\r\n'
        self.parse_response(r)
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.status, 200)
        self.assertEqual(ro.headers, [('Transfer-Encoding', 'chunked')])
        self.assertEqual(ro.get_header('Transfer-Encoding'), 'chunked')
        self.assertEqual(ro.trailers, [('ETag', 'foo')])
        self.assertEqual(ro.get_trailer('ETag'), 'foo')
        self.assertEqual(ro.read(), b'Foo')
        self.assertEqual(ro.read(), b'')

    def test_pipelined_responses(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nSet-Cookie: foo=0\r\n\r\n' \
            b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nSet-Cookie: foo=1\r\n\r\n'
        self.parse_response(r)
        for i in range(2):
            ro = self.getresponse()
            self.assertEqual(ro.version, '1.1')
            self.assertEqual(ro.status, 200)
            cookie = 'foo={0}'.format(i)
            self.assertEqual(ro.headers, [('Content-Length', '0'), ('Set-Cookie', cookie)])
            self.assertEqual(ro.read(), b'')

    def test_pipelined_responses_with_body(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nFoo0' \
            b'HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nFoo1'
        self.parse_response(r)
        for i in range(2):
            ro = self.getresponse()
            self.assertEqual(ro.version, '1.1')
            self.assertEqual(ro.status, 200)
            self.assertEqual(ro.headers, [('Content-Length', '4')])
            self.assertEqual(ro.read(), 'Foo{0}'.format(i).encode('ascii'))
            self.assertEqual(ro.read(), b'')

    def test_pipelined_head_responses(self):
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n' \
            b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n'
        self.parse_response(r, methods=['HEAD', 'HEAD'])
        for i in range(2):
            ro = self.getresponse()
            self.assertEqual(ro.version, '1.1')
            self.assertEqual(ro.status, 200)
            self.assertEqual(ro.headers, [('Content-Length', '3')])
            self.assertEqual(ro.read(), b'')

    def test_pipelined_empty_responses(self):
        r = b'HTTP/1.1 100 OK\r\nCookie: foo0\r\n\r\n' \
            b'HTTP/1.1 204 OK\r\nCookie: foo1\r\n\r\n' \
            b'HTTP/1.1 304 OK\r\nCookie: foo2\r\n\r\n'
        self.parse_response(r)
        for i in range(3):
            ro = self.getresponse()
            self.assertEqual(ro.version, '1.1')
            self.assertEqual(ro.headers, [('Cookie', 'foo{0}'.format(i))])
            self.assertEqual(ro.read(), b'')

    def test_pipelined_200_response_eof(self):
        # No content-length so 200 requires and EOF to indicate the end of
        # message. The second request is therefore interpreted as a the body of
        # the first.
        r = b'HTTP/1.1 200 OK\r\nCookie: foo0\r\n\r\nfoo'
        self.parse_response(r)
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.headers, [('Cookie', 'foo0')])
        self.assertEqual(ro.read(3), b'foo')
        self.assertFalse(ro._message.body.eof)
        self.protocol.connection_lost(None)
        self.assertTrue(ro._message.body.eof)
        self.assertEqual(ro.read(), b'')

    def test_pipelined_204_response_eof(self):
        # A 204 never has a body so the absence of a Content-Length header
        # still does not require it to see an EOF.
        r = b'HTTP/1.1 204 OK\r\nCookie: foo0\r\n\r\n'
        self.parse_response(r)
        ro = self.getresponse()
        self.assertEqual(ro.version, '1.1')
        self.assertEqual(ro.headers, [('Cookie', 'foo0')])
        self.assertEqual(ro.read(), b'')


def hello_app(environ, start_response):
    headers = [('Content-Type', 'text/plain')]
    start_response('200 OK', headers)
    return ['Hello!']


def echo_app(environ, start_response):
    headers = [('Content-Type', 'text/plain')]
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
        response = client.getresponse()
        self.assertEqual(response.version, '1.1')
        self.assertEqual(response.status, 200)
        ident = response.get_header('Server')
        self.assertTrue(ident.startswith('gruvi'))
        ctype = response.get_header('Content-Type')
        self.assertEqual(ctype, 'text/plain')
        self.assertEqual(response.read(), b'Hello!')
        server.close()
        client.close()

    def test_simple_pipe(self):
        server = HttpServer(hello_app)
        server.listen(self.pipename())
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('GET', '/')
        response = client.getresponse()
        self.assertEqual(response.read(), b'Hello!')
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
        response = client.getresponse()
        self.assertEqual(response.read(), b'Hello!')
        server.close()
        client.close()

    def test_request_body_bytes(self):
        server = HttpServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('POST', '/', body=b'foo')
        response = client.getresponse()
        body = response.read()
        self.assertEqual(body, b'foo')
        server.close()
        client.close()

    def test_request_body_string(self):
        # When making a request with a string body, it should be encoded as
        # ISO-8859-1.
        server = HttpServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('POST', '/', body='foo')
        response = client.getresponse()
        body = response.read()
        self.assertEqual(body, b'foo')
        server.close()
        client.close()

    def test_request_body_sequence(self):
        server = HttpServer(echo_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        client.request('POST', '/', body=[b'foo', 'bar'])
        response = client.getresponse()
        body = response.read()
        self.assertEqual(body, b'foobar')
        server.close()
        client.close()


if __name__ == '__main__':
    unittest.main()
