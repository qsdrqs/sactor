#include <stdio.h>
#include <stdlib.h>

enum Days {
    MON = 1,
    TUE = 2,
    WED = 3,
    THU = 4,
    FRI = 5,
    SAT = 6,
    SUN = 7
};

int main(int argc, char *argv[]) {
    int day;
    if (argc != 2) {
        printf("Usage: %s <day number>\n", argv[0]);
        return 1;
    }
    day = atoi(argv[1]);
    if (day < MON || day > SUN) {
        printf("Invalid day number, should be between 1 and 7\n");
        return 1;
    }
    enum Days today = (enum Days)day;
    printf("Day number: %d\n", today);
    return 0;
}

enum Days foo(enum Days e) {
    return e;
}
