typedef enum {
    A,
    B,
    C
} my_enum;

int main() {
    my_enum e = A;
    if (e == B) {
        return 1;
    } else if (e == C) {
        return 2;
    }
    return 0;
}
