#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import gruvi
from gruvi.test import UnitTest
import inspect


class TestHub(UnitTest):

    def test_switchpoint(self):
        def func(foo, bar, baz=None, *args, **kwargs):
            """Foo bar."""
            return (foo, bar, baz, args, kwargs)
        wrapper = gruvi.switchpoint(func)
        assert wrapper.__name__ == 'func'
        assert wrapper.__doc__.endswith('switchpoint.*\n')
        argspec = inspect.getargspec(wrapper)
        assert argspec.args == ['foo', 'bar', 'baz']
        assert argspec.varargs == 'args'
        assert argspec.keywords == 'kwargs'
        assert argspec.defaults == (None,)
        result = wrapper(1, 2, qux='foo')
        assert result == (1, 2, None, (), { 'qux': 'foo'})
        result = wrapper(1, 2, 3, 4, qux='foo')
        assert result == (1, 2, 3, (4,), { 'qux': 'foo'})
