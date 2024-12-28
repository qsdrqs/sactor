from sactor.verifier import UnidiomaticVerifier, VerifyResult

'''
return0stderr
return0stdout
return1stderr
return1stdout
return1stdoutstderr
'''
def test_run_tests1():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return0stdout")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.SUCCESS
    assert result[1] == None

def test_run_tests2():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return0stderr")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.SUCCESS
    assert result[1] == None

def test_run_tests3():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return1stdout")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Hello, world!\n"

def test_run_tests4():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return1stderr")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Some error message\n"

def test_run_tests5():
    verifier = UnidiomaticVerifier("tests/verifier/mock_results/return1stdoutstderr")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Some error message\n"
