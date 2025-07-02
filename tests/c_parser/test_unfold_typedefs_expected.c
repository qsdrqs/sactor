#include <stdio.h>



struct node {
    int data;
    struct node* next;
};

struct point {
    int x;
    int y;
};



void print_node(struct node* n) { printf("%d\n", n->data); }

void print_point(struct point p) { printf("%d, %d\n", p.x, p.y); }

int main() {
    struct node n1;
    n1.data = 10;
    n1.next = NULL;

    struct node n2;
    n2.data = 20;
    n2.next = &n1;

    struct point p1;
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
