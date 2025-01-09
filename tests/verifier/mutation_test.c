#include <stdio.h>

static
int add(int a, int b);

int main()
{
    int a = 1;
    int b = 2;
    int c = add(a, b);
    printf("c = %d\n", c);
    return 0;
}

static 
int add(int a, int b)
{
    return a + b;
}
