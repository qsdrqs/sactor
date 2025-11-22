// Leading non-ASCII: byte/codepoint mapping check （测）
int conditional_demo(int x) {
#if 0
    return x + 1;
#else
    return x + 2;
#endif
}
