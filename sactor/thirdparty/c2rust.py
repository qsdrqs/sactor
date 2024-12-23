import shutil
import os
import subprocess
import tempfile


def _include_path():
    if shutil.which("gcc"):
        compiler = "gcc"
    elif shutil.which("clang"):
        compiler = "clang"
    else:
        raise OSError("No C compiler found")
    cmd = [compiler, '-v', '-E', '-x', 'c', '/dev/null']
    result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    compile_output = result.stderr.decode()
    search_include_paths = []

    add_include_path = False
    for line in compile_output.split('\n'):
        if line.startswith('#include <...> search starts here:'):
            add_include_path = True
            continue
        if line.startswith('End of search list.'):
            break

        if add_include_path:
            search_include_paths.append(line.strip())

    return search_include_paths


def get_c2rust_translation(filename):
    # check c2rust executable
    if not shutil.which("c2rust"):
        print("c2rust executable not found")
        raise OSError("c2rust executable not found")

    with tempfile.TemporaryDirectory() as tmpdir:
        filename_noext = os.path.splitext(filename)[0]
        tmp_filename = os.path.join(tmpdir, os.path.basename(filename))
        tmp_filename_rs = os.path.join(tmpdir, os.path.basename(filename_noext + ".rs"))
        shutil.copy(filename, tmp_filename)

        # run c2rust
        search_include_paths = _include_path()
        search_include_paths = [f'-I{path}' for path in search_include_paths]
        cmd = ['c2rust', 'transpile', tmp_filename, '--', *search_include_paths]
        print(cmd)
        # add C_INCLUDE_PATH to the environment if needed
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("c2rust failed")
            os.remove(tmp_filename_rs)
            raise RuntimeError("c2rust transpile command failed")

        # this is the translated Rust code
        assert os.path.exists(tmp_filename_rs)

        with open(tmp_filename_rs) as f:
            c2rust_content = f.read()

    return c2rust_content

