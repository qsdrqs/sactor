#include <string.h>

#define RNG_BAD_MAXLEN -1
#define RNG_SUCCESS 0

typedef struct {
    unsigned long length_remaining;
    unsigned char key[32];
    unsigned char ctr[16];
    unsigned char buffer_pos;
    unsigned char buffer[16];
} AES_XOF_struct;

int seedexpander_init(AES_XOF_struct *ctx,
                      unsigned char *seed,
                      unsigned char *diversifier,
                      unsigned long maxlen) {
    if (maxlen >= 0x100000000)
        return RNG_BAD_MAXLEN;

    ctx->length_remaining = maxlen;
    memcpy(ctx->key, seed, 32);
    memcpy(ctx->ctr, diversifier, 8);
    ctx->buffer_pos = 0;
    return RNG_SUCCESS;
}
