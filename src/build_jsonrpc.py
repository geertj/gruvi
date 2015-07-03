#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2015 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os.path
from cffi import FFI

parent, _ = os.path.split(os.path.abspath(__file__))
topdir, _ = os.path.split(parent)


ffi = FFI()

ffi.set_source('jsonrpc_ffi', """
    #include "src/json_splitter.c"
    """, include_dirs=[topdir])

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


if __name__ == '__main__':
    ffi.compile()
