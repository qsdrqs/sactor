#define INNER(x) ((x) + 1)
#define MID(y) (INNER(y) * (y))
#define OUTER(z) MID(z)

int use_macros(int v) {
    return OUTER(v);
}
