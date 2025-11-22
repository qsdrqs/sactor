#include <stdint.h>

#define OUTER(z) ((z) + 1)

int macro_sample(int x) {
#define DOUBLE(y) ((y) * 2)
    return DOUBLE(x) + OUTER(x);
}
