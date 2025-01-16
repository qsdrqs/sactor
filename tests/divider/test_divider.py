from sactor.divider import Divider
from sactor.c_parser import CParser
import pytest


class MockInfo:
    def __init__(self, name, dependencies):
        self.name = name
        self.dependencies = dependencies

    def get_dependencies(self):
        return self.dependencies

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name

@pytest.fixture
def divider():
    c_parser = CParser('tests/c_examples/course_manage/course_manage.c')
    return Divider(c_parser)

def test_extract_order1(divider):
    # Test case 1: A->B, B->[C,A], C->[], D->[]
    a = MockInfo("A", [])
    b = MockInfo("B", [])
    c = MockInfo("C", [])
    d = MockInfo("D", [])

    a.dependencies = [b]
    b.dependencies = [c, a]

    test1_lst = [a, b, c, d]
    result1 = divider._extract_order(test1_lst, lambda x: x.get_dependencies())
    assert (result1 == [[c], [d], [a, b]] or
            result1 == [[d], [c], [a, b]])

def test_extract_order2(divider):
    # Test case 2: A->B->C->[], D->A, E->[]
    a = MockInfo("A", [])
    b = MockInfo("B", [])
    c = MockInfo("C", [])
    d = MockInfo("D", [])
    e = MockInfo("E", [])

    a.dependencies = [b]
    b.dependencies = [c]
    d.dependencies = [a]

    test2_lst = [a, b, c, d, e]
    result2 = divider._extract_order(test2_lst, lambda x: x.get_dependencies())
    assert (result2 == [[c], [e], [b], [a], [d]] or
            result2 == [[e], [c], [b], [a], [d]])

def test_extract_order3(divider):
    # Test case 3: A->B->D, A->C->D, E->A, D->[], F->[]
    a = MockInfo("A", [])
    b = MockInfo("B", [])
    c = MockInfo("C", [])
    d = MockInfo("D", [])
    e = MockInfo("E", [])
    f = MockInfo("F", [])

    a.dependencies = [b, c]
    b.dependencies = [d]
    c.dependencies = [d]
    e.dependencies = [a]

    test3_lst = [a, b, c, d, e, f]
    result3 = divider._extract_order(test3_lst, lambda x: x.get_dependencies())
    assert (result3 == [[d], [f], [b], [c], [a], [e]] or
            result3 == [[f], [d], [b], [c], [a], [e]] or
            result3 == [[d], [f], [c], [b], [a], [e]] or
            result3 == [[f], [d], [c], [b], [a], [e]])

def test_extract_order4(divider):
    # Test case 1: A->[B, C], B->C, C->[B, D], D->[]
    a = MockInfo("A", [])
    b = MockInfo("B", [])
    c = MockInfo("C", [])
    d = MockInfo("D", [])

    a.dependencies = [b, c]
    b.dependencies = [c]
    c.dependencies = [b, d]
    d.dependencies = []

    test4_lst = [a, b, c, d]
    result1 = divider._extract_order(test4_lst, lambda x: x.get_dependencies())
    assert result1 == [[d], [b, c], [a]]

def test_function_order(divider):
    function_order = divider.get_function_order()
    function_order_name = [[f.name for f in lst] for lst in function_order]
    assert function_order_name == [['printUsage'], ['updateStudentInfo'], ['main']]

def test_struct_order(divider):
    struct_order = divider.get_struct_order()
    struct_order_name = [[s.name for s in lst] for lst in struct_order]
    assert struct_order_name == [['Course'], ['Student']]