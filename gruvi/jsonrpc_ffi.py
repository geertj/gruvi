#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os.path
from cffi import FFI

__all__ = []


ffi = FFI()
ffi.cdef("""
    #define OK ...
    #define INCOMPLETE ...
    #define ERROR ...

    struct split_context {
        const char *buf;
        int buflen;
        int offset;
        int error;
        ...;
    };

    int json_split(struct split_context *ctx);
""")

parent, _ = os.path.split(os.path.abspath(__file__))
topdir, _ = os.path.split(parent)
lib = ffi.verify("""
        #include "src/json_splitter.c"
        """, modulename='_jsonrpc_ffi', ext_package='gruvi', include_dirs=[topdir])
