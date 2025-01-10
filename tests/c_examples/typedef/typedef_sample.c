#include <stdio.h>
#include <stdlib.h>
#include <math.h>

typedef struct {
    float x;
    float y;
} Point;

typedef Point Vector;

float calculate_distance(Vector p1, Vector p2) {
    float dx = p2.x - p1.x;
    float dy = p2.y - p1.y;
    return sqrt(dx * dx + dy * dy);
}

int main(int argc, char *argv[]) {
    if (argc != 5) {
        printf("Usage: %s x1 y1 x2 y2\n", argv[0]);
        printf("Example: %s 0 0 3 4\n", argv[0]);
        return 1;
    }

    Point p1 = {
        .x = atof(argv[1]),
        .y = atof(argv[2])
    };

    Point p2 = {
        .x = atof(argv[3]),
        .y = atof(argv[4])
    };

    printf("Point 1: (%.1f, %.1f)\n", p1.x, p1.y);
    printf("Point 2: (%.1f, %.1f)\n", p2.x, p2.y);
    printf("Distance: %.1f\n", calculate_distance(p1, p2));

    return 0;
}
