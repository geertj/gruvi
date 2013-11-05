/*
 * This file is part of Gruvi. Gruvi is free software available under the
 * terms of the MIT license. See the file "LICENSE" that was provided
 * together with this source file for the licensing terms.
 *
 * Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
 * complete list.
 *
 * This file contains a high performance incremental D-BUS splitter. It is
 * exposed to Python via CFFI.
 */

#include <stdio.h>

#define OK 0
#define INCOMPLETE 1
#define ERROR_ENDIAN 2
#define ERROR_TYPE 3
#define ERROR_FLAGS 4
#define ERROR_VERSION 5
#define ERROR_SERIAL 6
#define ERROR_TOO_LARGE 7

struct context
{
    const char *buf;
    int buflen;
    int offset;
    int error;
    int state;
    int big_endian;
    int msglen;
    int serial;
};


static int split(struct context *ctx)
{
    int byteidx, avail, needed, skip;
    unsigned char ch;

    ctx->error = 0;
    while (ctx->offset < ctx->buflen)
    {
        /* Fast path if we are just counting the body bytes. */
        if (ctx->state > 15) {
            avail = ctx->buflen - ctx->offset;
            needed = ctx->msglen - ctx->state;
            skip = (needed <= avail) ? needed : avail;
            ctx->state += skip;
            ctx->offset += skip;
            break;
        }

        ch = ctx->buf[ctx->offset];

        /* State is the offset into the message. */
        switch (ctx->state)
        {
        case 0:  /* Endianness */
            if (ch == 'B')
                ctx->big_endian = 1;
            else if (ch != 'l')
                ctx->error = ERROR_ENDIAN;
            break;
        case 1:  /* Message type */
            if (ch == 0 || ch > 4)
                ctx->error = ERROR_TYPE;
            break;
        case 2:  /* Message flags */
            if (ch & ~0x3)
                ctx->error = ERROR_FLAGS;
            break;
        case 3:  /* Protocol version */
            if (ch != 1)
                ctx->error = ERROR_VERSION;
            break;
        case 4: case 5: case 6: case 7:   /* Body length */
            if (ctx->state == 4)
                ctx->msglen = 16;  /* minimum header size */
            byteidx = ctx->big_endian ? (7 - ctx->state) : (ctx->state - 4);
            ctx->msglen += (ch << (8 * byteidx));
            break;
        case 8: case 9: case 10: case 11:  /* Message serial */
            byteidx = ctx->big_endian ? (11 - ctx->state) : (ctx->state - 8);
            ctx->serial += (ch << (8 * byteidx));
            if ((ctx->state == 11) && (ctx->serial == 0))
                ctx->error = ERROR_SERIAL;  /* May not be zero */
            break;
        case 12: case 13: case 14: case 15:  /* Extra header fields length */
            byteidx = ctx->big_endian ? (15 - ctx->state) : (ctx->state - 12);
            ctx->msglen += (ch << (8 * byteidx));
            if ((ctx->state == 12 && !ctx->big_endian) ||
                        (ctx->state == 15 && ctx->big_endian))
                ctx->msglen += (256 - ch) % 8;  /* Header padding */
            break;
        }

        if (ctx->msglen > 0x10000000)
            ctx->error = ERROR_TOO_LARGE;
        if (ctx->error)
            break;
        ctx->offset++;
        ctx->state++;

    }

    if (!ctx->error) {
        if (ctx->state == ctx->msglen)
            ctx->state = 0;
        else
            ctx->error = INCOMPLETE;
    }

    return ctx->error;
}
