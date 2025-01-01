#include <stdio.h>
#include <stdlib.h>

int add(int a, int b)
{
    return a + b;
}

int main(int argc, char *argv[])
{
    // get the arguments
    if (argc != 3)
    {
        printf("Usage: %s <num1> <num2>\n", argv[0]);
        return 1;
    }
    int a = atoi(argv[1]);
    int b = atoi(argv[2]);
    int c = add(a, b);
    printf("%d + %d = %d\n", a, b, c);
    return 0;
}
