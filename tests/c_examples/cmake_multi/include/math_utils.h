#ifndef CMAKE_MULTI_MATH_UTILS_H
#define CMAKE_MULTI_MATH_UTILS_H

#include <stddef.h>

int add_integers(int lhs, int rhs);
int multiply_integers(int lhs, int rhs);
int dot_product(const int *lhs, const int *rhs, size_t length);

#endif /* CMAKE_MULTI_MATH_UTILS_H */
