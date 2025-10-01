struct example_token_impl {
    unsigned char bits;
};

typedef struct example_token_impl example_token;

void write_example(example_token *token);
