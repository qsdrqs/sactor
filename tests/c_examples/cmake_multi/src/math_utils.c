#include "math_utils.h"

int add_integers(int lhs, int rhs) {
    return lhs + rhs;
}

int multiply_integers(int lhs, int rhs) {
    return lhs * rhs;
}

int dot_product(const int *lhs, const int *rhs, size_t length) {
    int total = 0;
    for (size_t i = 0; i < length; ++i) {
        total += lhs[i] * rhs[i];
    }
    return total;
}
