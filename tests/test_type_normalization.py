from sactor.type_normalization import (
    get_libc_scalar_map,
    get_libc_scalar_pairs,
    iter_numeric_primitives,
    map_libc_scalar,
)


def test_get_libc_scalar_map_contains_expected_entries():
    mapping = get_libc_scalar_map()
    assert mapping["libc::c_int"] == "i32"
    assert mapping["libc::size_t"] == "usize"
    assert tuple(get_libc_scalar_pairs())[0][0].startswith("libc::")


def test_map_libc_scalar_accepts_prefixed_and_unprefixed_names():
    assert map_libc_scalar("libc::c_uint") == "u32"
    assert map_libc_scalar("c_uint") == "u32"
    assert map_libc_scalar("unknown_type") is None


def test_iter_numeric_primitives_order():
    primitives = list(iter_numeric_primitives())
    assert primitives[0] == "u8"
    assert primitives[-1] == "f64"
    assert len(primitives) == len(set(primitives))
