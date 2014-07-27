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

from gruvi.dbus import DbusClient, DbusServer
from support import PerformanceTest
from test_dbus import echo_app


class PerfDBus(PerformanceTest):

    def perf_message_throughput_pipe(self):
        # Test roundtrips of a simple method call over a Pipe
        server = DbusServer(echo_app)
        addr = 'unix:path=' + self.pipename()
        server.listen(addr)
        client = DbusClient()
        client.connect(addr)
        nmessages = 0
        t0 = t1 = time.time()
        while t1 - t0 < 0.2:
            client.call_method('bus.name', '/path', 'my.iface', 'Echo')
            t1 = time.time()
            nmessages += 1
        throughput = nmessages / (t1 - t0)
        self.add_result(throughput)
        server.close()
        client.close()

    def perf_message_throughput_tcp(self):
        # Test roundtrips of a simple method call over TCP.
        server = DbusServer(echo_app)
        addr = 'tcp:host=127.0.0.1,port=0'
        server.listen(addr)
        client = DbusClient()
        client.connect(server.addresses[0])
        nmessages = 0
        t0 = t1 = time.time()
        while t1 - t0 < 0.2:
            client.call_method('bus.name', '/path', 'my.iface', 'Echo')
            t1 = time.time()
            nmessages += 1
        throughput = nmessages / (t1 - t0)
        self.add_result(throughput)
        server.close()
        client.close()


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
