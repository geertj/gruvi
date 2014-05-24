# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import sys
from pyuv.error import UVError

__all__ = ['Error', 'Timeout', 'Cancelled']

Error = UVError

class Timeout(Error):
    """A timeout has occurred."""

class Cancelled(Error):
    """A fiber or calback was cancelled."""


# The following is a pretty bad hack.. We want to use Sphinx's "automodule" to
# document most of our modules in the API reference section, and we want it to
# show inherited members. The result is that it shows an ugly "with_traceback"
# method for gruvi.Error. We fix that by setting that method to None if and
# only if we are running under Sphinx.

if hasattr(sys, 'running_under_sphinx'):
    Error.with_traceback = None
