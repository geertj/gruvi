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

from gruvi.jsonrpc import JsonRpcClient, JsonRpcServer
from gruvi import jsonrpc_ffi

from support import PerformanceTest
from test_jsonrpc import set_buffer, echo_app


class PerfJsonRpc(PerformanceTest):

    def perf_split_throughput(self):
        chunk = b'{' + b'x' * 1000 + b'}'
        buf = chunk * 10
        ctx = jsonrpc_ffi.ffi.new('struct split_context *')
        nbytes = 0
        t0 = t1 = time.time()
        while t1 - t0 < 1:
            set_buffer(ctx, buf)
            while ctx.offset != len(buf):
                error = jsonrpc_ffi.lib.json_split(ctx)
                self.assertEqual(error, 0)
            nbytes += len(buf)
            t1 = time.time()
        speed = nbytes / (t1 - t0) / (1024 * 1024)
        self.add_result(speed)

    def perf_message_throughput(self):
        server = JsonRpcServer(echo_app)
        server.listen(('127.0.0.1', 0))
        addr = server.addresses[0]
        client = JsonRpcClient()
        client.connect(addr)
        nrequests = 0
        t0 = t1 = time.time()
        while t1 - t0 < 1:
            result = client.call_method('echo', 'foo')
            self.assertEqual(result, ['foo'])
            nrequests += 1
            t1 = time.time()
        throughput = nrequests / (t1 - t0)
        self.add_result(throughput)
        server.close()
        client.close()


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
