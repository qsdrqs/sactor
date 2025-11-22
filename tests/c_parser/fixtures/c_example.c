#include <stdio.h>

// Define a struct
struct Point {
    int x;
    int y;
};

// Function that takes a struct Point as an argument
void printPoint(struct Point p) {
    printf("Point coordinates: (%d, %d)\n", p.x, p.y);
}

// doesn't have struct in the signature
void foo() {
    struct Point p2 = {30, 40};
    printPoint(p2);
}

int main() {
    // Create an instance of struct Point
    struct Point p1 = {10, 20};

    // Call the function with the struct as an argument
    printPoint(p1);

    return 0;
}
