#include <stdint.h>
#include <stddef.h>

struct SampleBuffer {
    long *values;
    size_t length;
};

int buffer_apply(struct SampleBuffer *buffer, long value) {
    long shift = (long)(value + buffer->values[0]);
    return shift > 0 ? (long)shift : (long)(shift + (long)buffer->length);
}
