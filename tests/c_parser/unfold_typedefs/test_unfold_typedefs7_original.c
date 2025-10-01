#include <stdint.h>
#include <stddef.h>

typedef int64_t SampleValue;

typedef struct {
    SampleValue *values;
    size_t length;
} SampleBuffer;

int buffer_apply(SampleBuffer *buffer, SampleValue value) {
    SampleValue shift = (SampleValue)(value + buffer->values[0]);
    return shift > 0 ? (SampleValue)shift : (SampleValue)(shift + (SampleValue)buffer->length);
}
