enum my_enum {
    A,
    B,
    C
};

int main() {
    enum my_enum e = A;
    if (e == B) {
        return 1;
    } else if (e == C) {
        return 2;
    }
    return 0;
}
