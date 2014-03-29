#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import time

from gruvi.ssl import SSLPipe
from tests.support import *
from tests.test_ssl import communicate


class PerfSSL(PerformanceTest):

    def perf_ssl_throughput(self):
        server = SSLPipe(keyfile=self.certname, certfile=self.certname, server_side=True)
        client = SSLPipe(server_side=False)
        buf = b'x' * 65536
        nbytes = 0
        clientssl = client.start_handshake()
        server.start_handshake()
        t0 = t1 = time.time()
        while t1 - t0 < 1:
            received = communicate(buf, client, server, clientssl, [])
            if clientssl:
                clientssl = []
            nbytes += len(received)
            t1 = time.time()
        speed = nbytes / (t1 - t0) / (1024 * 1024)
        self.add_result(speed)
        client.close()
        server.close()


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
