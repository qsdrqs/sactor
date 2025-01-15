from sactor import utils
from sactor.verifier import UnidiomaticVerifier, VerifyResult


def get_unidiomatic_verifier(test_cmd_path):
    config = utils.load_default_config()
    return UnidiomaticVerifier(test_cmd_path, config=config)

def test_run_tests1():
    verifier = get_unidiomatic_verifier("tests/verifier/mock_results/return0stdout.json")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.SUCCESS
    assert result[1] == None


def test_run_tests2():
    verifier = get_unidiomatic_verifier("tests/verifier/mock_results/return0stderr.json")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.SUCCESS
    assert result[1] == None


def test_run_tests3():
    verifier = get_unidiomatic_verifier("tests/verifier/mock_results/return1stdout.json")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Hello, world!\n"


def test_run_tests4():
    verifier = get_unidiomatic_verifier("tests/verifier/mock_results/return1stderr.json")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Some error message\n"


def test_run_tests5():
    verifier = get_unidiomatic_verifier(
        "tests/verifier/mock_results/return1stdoutstderr.json")
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_ERROR
    assert result[1] == "Some error message\n"

def test_run_timeout():
    verifier = get_unidiomatic_verifier(
        "tests/verifier/mock_results/timeout.json")
    verifier.config['general']['timeout_seconds'] = 2
    result = verifier._run_tests("")
    assert result[0] == VerifyResult.TEST_TIMEOUT
    print(result[1])


