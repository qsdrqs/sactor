#include <stdio.h>

typedef struct node node_t;
typedef struct node {
    int data;
    node_t* next;
} node_t

;

struct point {
    int x;
    int y;
};

typedef struct point point_t;

void print_node(node_t* n) { printf("%d\n", n->data); }

void print_point(point_t p) { printf("%d, %d\n", p.x, p.y); }

int main() {
    node_t n1;
    n1.data = 10;
    n1.next = NULL;

    struct node n2;
    n2.data = 20;
    n2.next = &n1;

    point_t p1;
    p1.x = 1;
    p1.y = 2;

    struct point p2;
    p2.x = 3;
    p2.y = 4;

    print_node(&n1);
    print_node(&n2);
    print_point(p1);
    print_point(p2);

    return 0;
}
