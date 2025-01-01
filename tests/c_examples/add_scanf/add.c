#include <stdio.h>
#include <stdlib.h>

int add(int a, int b)
{
    return a + b;
}

int main(int argc, char *argv[])
{
    // get the arguments
    int a, b;
    printf("Enter two numbers: ");
    scanf("%d %d", &a, &b);
    int c = add(a, b);
    printf("%d + %d = %d\n", a, b, c);
    return 0;
}
