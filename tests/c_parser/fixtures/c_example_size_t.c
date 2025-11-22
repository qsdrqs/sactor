#include <stddef.h>
#include <stdio.h>


int foo(size_t length);

int main() {
    size_t length = 10;
    printf("length: %d\n", foo(length));
    return 0;
}

int foo(size_t length) {
    return length;
}
