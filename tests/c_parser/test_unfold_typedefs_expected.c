#include <stdio.h>



typedef int (*operation_fn)(int a, int b);

struct node {
    int data;
    struct node* next;
};

struct point_t {
    int x;
    int y;
};

void print_node(struct node* n) { printf("%d\n", n->data); }

void print_point(struct point_t p) { printf("%d, %d\n", p.x, p.y); }

void test(operation_fn op) {
    int result = op(3, 4);
    printf("Result of operation: %d\n", result);
}

int main() {
    struct node n1;
    n1.data = 10;
    n1.next = NULL;

    struct node n2;
    n2.data = 20;
    n2.next = &n1;

    struct point_t p1;
    p1.x = 1;
    p1.y = 2;

    struct point_t p2;
    p2.x = 3;
    p2.y = 4;

    print_node(&n1);
    print_node(&n2);
    print_point(p1);
    print_point(p2);

    return 0;
}
