#include "stats.h"

#include <float.h>

double average(const int *values, size_t length) {
    if (length == 0) {
        return 0.0;
    }

    long sum = 0;
    for (size_t i = 0; i < length; ++i) {
        sum += values[i];
    }
    return (double)sum / (double)length;
}

int max_value(const int *values, size_t length) {
    if (length == 0) {
        return 0;
    }

    int current_max = values[0];
    for (size_t i = 1; i < length; ++i) {
        if (values[i] > current_max) {
            current_max = values[i];
        }
    }
    return current_max;
}
