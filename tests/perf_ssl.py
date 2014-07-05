#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function, division

import os
import time
import ssl

from gruvi.ssl import SslPipe
from support import PerformanceTest, unittest, SkipTest
from test_ssl import communicate

if hasattr(ssl, 'SSLContext'):
    from ssl import SSLContext
else:
    from gruvi.sslcompat import SSLContext


class PerfSsl(PerformanceTest):

    def setUp(self):
        if not os.access(self.certname, os.R_OK):
            raise SkipTest('no certificate available')
        super(PerfSsl, self).setUp()
        context = SSLContext(ssl.PROTOCOL_SSLv23)
        context.load_cert_chain(self.certname, self.certname)
        self.client = SslPipe(context, False)
        self.server = SslPipe(context, True)

    def perf_throughput(self):
        client, server = self.client, self.server
        buf = b'x' * 65536
        nbytes = 0
        clientssl = client.do_handshake()
        server.do_handshake()
        t0 = t1 = time.time()
        while t1 - t0 < 1:
            received = communicate(buf, client, server, clientssl, [])
            if clientssl:
                clientssl = []
            nbytes += len(received)
            t1 = time.time()
        cipher = server.sslsocket.cipher()[0].lower().replace('-', '_')
        name = 'ssl_throughput_{0}'.format(cipher)
        speed = nbytes / (t1 - t0) / (1024 * 1024)
        self.add_result(speed, name=name)
        client.close()
        server.close()


if __name__ == '__main__':
    unittest.defaultTestLoader.testMethodPrefix = 'perf'
    unittest.main()
