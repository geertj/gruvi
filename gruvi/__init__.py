#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

# Suppress warnings about 'import *' here. The submodules are designed to
# export their symbols to a global package namespace like this.
# flake8: noqa

# should not use "from gruvi import *"
__all__ = []

import sys
if sys.version_info[0] == 2 and sys.version_info[1] < 7 \
        or sys.version_info[0] == 3 and sys.version_info[1] < 3:
    raise ImportError('Gruvi requires Python 2.7 or 3.3+')

# import all the subpackages into the "gruvi" namespace
from .errors import *
from .hub import *
from .fibers import *
from .sync import *
from .local import *
from .ssl import *
from .futures import *
from .transports import *
from .protocols import *
from .endpoints import *
from .address import *
from .process import *
from .stream import *
from .http import *
from .jsonrpc import *
from .dbus import *

# clean up module namespace
del sys, absolute_import, print_function
