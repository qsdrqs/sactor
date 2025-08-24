# Example for usage on ogg
```bash
cd [path to ogg]/src/
(Run automake commands until there is a Makefile in ./src)
intercept-build make check
sactor translate bitwise.c test_task.json -r ../sactor_result --type bin --unidiomatic-only -a "gcc -DHAVE_CONFIG_H -I. -I..  -I../include -I../include  -D_V_SELFTEST -O2 -Wall -Wextra -ffast-math -fsigned-char -g -O2 -MT test_bitwise-bitwise.o -MD -MP -MF .deps/test_bitwise-bitwise.Tpo -c -o test_bitwise-bitwise.o `test -f 'bitwise.c' || echo './'`bitwise.c
mv -f .deps/test_bitwise-bitwise.Tpo .deps/test_bitwise-bitwise.Po
/bin/bash ../libtool  --tag=CC   --mode=link gcc -D_V_SELFTEST -O2 -Wall -Wextra -ffast-math -fsigned-char -g -O2   -o test_bitwise test_bitwise-bitwise.o" -C ./compile_commands.json
```