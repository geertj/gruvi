#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

__all__ = ['Error', 'Timeout', 'Cancelled']


class Error(Exception):
    """Base class for Gruvi exceptions."""

class Timeout(Error):
    """A timeout has occurred."""

class Cancelled(BaseException):
    """A fiber or calback was cancelled."""
