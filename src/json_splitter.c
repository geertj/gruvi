/*
 * This file is part of Gruvi. Gruvi is free software available under the
 * terms of the MIT license. See the file "LICENSE" that was provided
 * together with this source file for the licensing terms.
 *
 * Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
 * complete list.
 *
 * This file contains a fast incremental JSON splitter. It is exposed to
 * Python via CFFI.
 */

#include <stdio.h>
#include <ctype.h>

#define OK 0
#define INCOMPLETE 1
#define ERROR 2

enum state { s_preamble = 0, s_object, s_string, s_string_escape };

struct context
{
    const char *buf;
    int buflen;
    int offset;
    int state;
    int depth;
    int error;
};

int split(struct context *ctx)
{
    char ch;

    ctx->error = 0;
    while (ctx->offset < ctx->buflen)
    {
        ch = ctx->buf[ctx->offset];

        switch (ctx->state)
        {
        case s_preamble:
            if (ch == '{') {
                ctx->state = s_object;
                ctx->depth = 1;
            } else if (!isspace(ch))
                ctx->error = ERROR;
            break;
        case s_object:
            if (ch == '{')
                ctx->depth += 1;
            else if (ch == '}') {
                ctx->depth -= 1;
            } else if (ch == '"')
                ctx->state = s_string;
            break;
        case s_string:
            if (ch == '"')
                ctx->state = s_object;
            else if (ch == '\\')
                ctx->state = s_string_escape;
            break;
        case s_string_escape:
            ctx->state = s_string;
            break;
        }

        if (ctx->error)
            break;
        ctx->offset += 1;

        if (ctx->state == s_object && ctx->depth == 0)
            break;
    }

    if (!ctx->error) {
        if (ctx->state == s_object && ctx->depth == 0)
            ctx->state = s_preamble;
        else
            ctx->error = INCOMPLETE;
    }

    return ctx->error;
}
