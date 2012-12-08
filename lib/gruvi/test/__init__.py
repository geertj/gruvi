#
# This file is part of gruvi. Gruvi is free software available under the terms
# of the MIT license. See the file "LICENSE" that was provided together with
# this source file for the licensing terms.
#
# Copyright (c) 2012 the gruvi authors. See the file "AUTHORS" for a complete
# list.

from __future__ import print_function

import shutil
import os.path
import tempfile
from nose import SkipTest


class UnitTest(object):
    """Base class for unit tests."""

    @classmethod
    def setup_class(cls):
        cls.tmpdir = tempfile.mkdtemp(__name__)

    @classmethod
    def tempname(cls, name):
        return os.path.join(cls.tmpdir, name)

    @classmethod
    def teardown_class(cls):
        shutil.rmtree(cls.tmpdir)
