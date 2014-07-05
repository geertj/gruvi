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
    typedef struct http_parser http_parser;
    typedef struct http_parser_settings http_parser_settings;

    typedef int (*http_data_cb) (http_parser*, const char *at, size_t length);
    typedef int (*http_cb) (http_parser*);

    enum http_parser_type { HTTP_REQUEST, HTTP_RESPONSE, HTTP_BOTH, ... };

    struct http_parser {
      unsigned short http_major;
      unsigned short http_minor;
      unsigned short status_code;
      unsigned char method;
      void *data;
      ...;
    };

    struct http_parser_settings {
      http_cb      on_message_begin;
      http_data_cb on_url;
      http_cb      on_status_complete;
      http_data_cb on_header_field;
      http_data_cb on_header_value;
      http_cb      on_headers_complete;
      http_data_cb on_body;
      http_cb      on_message_complete;
      ...;
    };

    void http_parser_init(http_parser *parser, enum http_parser_type type);
    size_t http_parser_execute(http_parser *parser,
                               const http_parser_settings *settings,
                               const char *data,
                               size_t len);

    int http_should_keep_alive(const http_parser *parser);
    const char *http_method_str(enum http_method m);
    const char *http_errno_name(enum http_errno err);

    /* Extra functions to extract bitfields not supported by cffi */
    unsigned char http_message_type(http_parser *parser);
    unsigned char http_errno(http_parser *parser);
    unsigned char http_is_upgrade(http_parser *parser);

""")


parent, _ = os.path.split(os.path.abspath(__file__))
topdir, _ = os.path.split(parent)

lib = ffi.verify("""
    #include <stdlib.h>
    #include "src/http_parser.h"
    #include "src/http_parser.c"

    unsigned char http_message_type(http_parser *p) { return p->type; }
    unsigned char http_errno(http_parser *p) { return p->http_errno; }
    unsigned char http_is_upgrade(http_parser *p) { return p->upgrade; }

    """, modulename='_http_ffi', ext_package='gruvi', include_dirs=[topdir])
