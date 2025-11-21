#include <stdio.h>

#include "math_utils.h"
#include "stats.h"

int main(void) {
    int values[] = {1, 2, 3, 4, 5};
    size_t length = sizeof(values) / sizeof(values[0]);

    int sum = add_integers(values[0], values[1]);
    int product = multiply_integers(values[2], values[3]);
    double avg = average(values, length);
    int max = max_value(values, length);

    int other[] = {5, 4, 3, 2, 1};
    int dot = dot_product(values, other, length);

    printf("sum=%d product=%d avg=%.2f max=%d dot=%d\n",
           sum, product, avg, max, dot);

    return 0;
}
