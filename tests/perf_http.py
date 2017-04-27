#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import time
import unittest

from gruvi.http import HttpProtocol, HttpServer, HttpClient
from support import PerformanceTest, MockTransport


def hello_app(environ, start_response):
    headers = [('Content-Type', 'text/plain')]
    start_response('200 OK', headers)
    return [b'Hello!']


class PerfHttp(PerformanceTest):

    def perf_parsing_speed(self):
        transport = MockTransport()
        protocol = HttpProtocol()
        transport.start(protocol)
        r = b'HTTP/1.1 200 OK\r\nContent-Length: 10000\r\n\r\n'
        r += b'x' * 10000
        reqs = 4 * r
        nbytes = 0
        t0 = t1 = time.time()
        while t1 - t0 < 0.2:
            protocol.data_received(reqs)
            del protocol._queue._heap[:]
            nbytes += len(reqs)
            t1 = time.time()
        speed = nbytes / (t1 - t0) / (1024 * 1024)
        self.add_result(speed)

    def perf_server_throughput(self):
        server = HttpServer(hello_app)
        server.listen(('localhost', 0))
        addr = server.addresses[0]
        client = HttpClient()
        client.connect(addr)
        nrequests = 0
        t0 = t1 = time.time()
        while t1 - t0 < 0.2:
            client.request('GET', '/')
            resp = client.getresponse()
            self.assertEqual(resp.body.read(), b'Hello!')
            nrequests += 1
            t1 = time.time()
        throughput = nrequests / (t1 - t0)
        self.add_result(throughput)
        server.close()
        client.close()


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
