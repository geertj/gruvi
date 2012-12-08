#
# This file is part of gruvi. Gruvi is free software available under the terms
# of the MIT license. See the file "LICENSE" that was provided together with
# this source file for the licensing terms.
#
# Copyright (c) 2012 the gruvi authors. See the file "AUTHORS" for a complete
# list.

import pyuv
import gruvi


def sleep(secs):
    hub = gruvi.Hub.get()
    timer = pyuv.Timer(hub.loop)
    hub.wait(timer, secs, 0)
    hub.switch()
