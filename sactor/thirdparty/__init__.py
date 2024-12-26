from .c2rust import C2Rust
from .crown import Crown, CrownType
from .thirdparty import ThirdParty


def check_all_dependencies():
    result = True
    result = result and C2Rust.check_dependency()
    result = result and Crown.check_dependency()

    return result


__all__ = [
    'C2Rust',
    'Crown',
    'CrownType',
    'ThirdParty',
    'check_all_dependencies',
]
