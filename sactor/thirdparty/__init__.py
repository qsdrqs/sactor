import shutil

from .c2rust import C2Rust
from .crown import Crown, CrownType
from .rustfmt import RustFmt
from .thirdparty import ThirdParty


def check_all_requirements() -> list[str]:
    result = []
    result.extend(C2Rust.check_requirements())
    result.extend(Crown.check_requirements())
    result.extend(RustFmt.check_requirements())

    # check valgrind
    if not shutil.which('valgrind'):
        result.append('valgrind')

    return result


__all__ = [
    'C2Rust',
    'Crown',
    'CrownType',
    'ThirdParty',
    'check_all_requirements',
]
