#include <stdio.h>

int global_var = 0;

int main(int argc, char *argv[])
{
    global_var = 1;
    fprintf(stdout, "global_var = %d\n", global_var);
    return 0;
}
