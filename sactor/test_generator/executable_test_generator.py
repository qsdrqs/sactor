import json
import os
import subprocess
from typing import override

from sactor import utils
from sactor.llm import llm_factory

from .test_generator import TestGenerator
from .test_generator_types import TestGeneratorResult


class ExecutableTestGenerator(TestGenerator):
    def __init__(
        self,
        file_path,
        test_samples,
        config_path=None,
        test_samples_path=None,
        executable=None,
        feed_as_arguments=True,
        input_document=None,
        whole_program=False,
    ):
        super().__init__(
            config_path=config_path,
            file_path=file_path,
            test_samples=test_samples,
            test_samples_path=test_samples_path,
            input_document=input_document,
        )
        self.feed_as_arguments = feed_as_arguments
        self.whole_program = whole_program

        if executable is None:
            # try to compile the file
            executable = utils.compile_c_executable(file_path)

        executable = os.path.abspath(executable) # get the absolute path
        self.executable = executable

        for sample in self.init_test_samples:
            self._execute_test_sample(sample)

    def _execute_test_sample(self, test_sample):
        # TODO: support error tests
        try:
            if self.feed_as_arguments:
                feed_input_str = f'{self.executable} {test_sample}'
                cmd = feed_input_str.split()
                result = subprocess.run(
                    self.valgrind_cmd + cmd,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            else:
                cmd = self.executable
                result = subprocess.run(
                    self.valgrind_cmd + [cmd],
                    input=test_sample.encode() + '\n'.encode(),
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            if result.returncode != 0:
                raise ValueError(
                    f"Failed to run the executable with the input: {result.stderr.decode()}"
                )
        except subprocess.TimeoutExpired as e:
            print(f"Timeout: {e}")
            raise ValueError(f"Timeout: {e}. Please check the input format.")

        # Rerun without valgrind
        if self.feed_as_arguments:
            feed_input_str = f'{self.executable} {test_sample}'
            cmd = feed_input_str.split()
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        else:
            cmd = self.executable
            result = subprocess.run(
                cmd,
                input=test_sample.encode() + '\n'.encode(),
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        assert result.returncode == 0 # should not fail
        return utils.normalize_string(result.stdout.decode() + result.stderr.decode())

    def _generate_test_impl(self, count, counter_examples=None, attempt=0) -> TestGeneratorResult:
        if count < 0:
            raise ValueError(f"Invalid count: {count}")

        if count == 0:
            # don't need to generate any test cases
            return TestGeneratorResult.SUCCESS

        if attempt >= self.max_attempts:
            print(f"Max attempts exceeded: {attempt}")
            return TestGeneratorResult.MAX_ATTEMPTS_EXCEEDED

        # Generate test cases
        prompt = ''
        system_message = "You are an expert to write end-to-end tests for a C program."

        if not self.whole_program:
            # only extract the main function
            c_code = self.c_parser.extract_function_code("main")
            if c_code is None:
                raise ValueError("No main function found in the C program")
        else:
            c_code = self.c_parser.get_code()

        prompt += f'''
The C program has the following main function:
```c
{c_code}
```
'''
        if self.input_document:
            prompt += f'''
The C program has the following inormation in its documentation:
{self.input_document}
'''
        if len(self.test_samples) > 0:
            prompt += f'''
The C program has the following test cases already written:
'''
            for i, sample in enumerate(self.test_samples):
                prompt += f'''
----INPUT {i}----
```
{sample}
```
----END INPUT {i}----
'''

        if counter_examples:
            prompt += f'''
The following test cases are generated before but invalid:
'''
            for i, sample in enumerate(counter_examples):
                prompt += f'''
----INPUT {i}----
```
{sample[0]}
```
----END INPUT {i}----
----OUTPUT {i}----
```
{sample[1]}
```
----END OUTPUT {i}----
'''
            prompt += f'''
Please only provide valid inputs for these test cases.
'''

        prompt += f'''
Please write {count} test cases for the C program (start from **i=1**). All test cases should be written with the following format:
----INPUT {{i}}---- (Start from i=1)
```
Your input i here, **DO NOT** provide any comments or extra information in this block
```
----END INPUT {{i}}----
----INPUT {{i+1}}----
```
Your input i+1 here, **DO NOT** provide any comments or extra information in this block
```
----END INPUT {{i+1}}----

You don't need to provide the expected output. The expected output will be generated by the system.
You should only provide **VALID** inputs for the target C program. You can provide some inputs to test the edge cases.
'''

        result = self.llm.query(prompt, override_system_message=system_message)
        success_count = 0
        for i in range(1, count + 1):
            try:
                test_case = utils.parse_llm_result(result, f"input {i}")
                self.test_samples.append(test_case[f"input {i}"].strip())
                success_count += 1
            except ValueError as _:
                print(f"Failed to parse the input {i}")
                return self._generate_test_impl(count - success_count, attempt=attempt+1)  # Retry

        # collect test cases
        counter_examples = []
        remaining_test_samples = []
        for i, sample in enumerate(self.test_samples):
            try:
                output = self._execute_test_sample(sample)
            except ValueError as e:
                counter_examples.append((sample, e))
                continue
            print(f"Test {i} verified")
            self.test_samples_output.append(
                {
                    "input": sample,
                    "output": output,
                }
            )
            remaining_test_samples.append(sample)

        self.test_samples = remaining_test_samples
        if len(counter_examples) > 0:
            # remove invalid test cases
            print(f"Counter examples: {len(counter_examples)}")
            return self._generate_test_impl(len(counter_examples), counter_examples, attempt=attempt+1)

        return TestGeneratorResult.SUCCESS


    @override
    def generate_tests(self, count) -> TestGeneratorResult:
        return self._generate_test_impl(count)

    @override
    def create_test_task(self, task_path, test_sample_path):
        '''
        Create the test task from the generated test samples
        '''
        self._check_runner_exist()

        pwd = os.getcwd()
        if task_path is None:
            task_path = f'{pwd}/test_task/test_task.json'
        if test_sample_path is None:
            test_sample_path = f'{pwd}/test_task/test_samples.json'

        task_path_dir = os.path.dirname(task_path)
        if task_path_dir:
            os.makedirs(task_path_dir, exist_ok=True)
        test_sample_path_dir = os.path.dirname(test_sample_path)
        if test_sample_path_dir:
            os.makedirs(test_sample_path_dir, exist_ok=True)

        # Write test samples to the test
        self.export_test_samples(test_sample_path)

        # Write the test task
        tasks = []
        for i in range(len(self.test_samples)):
            command = f'sactor run-tests --type bin {os.path.abspath(test_sample_path)} %t {i}'
            if self.feed_as_arguments:
                command += f' --feed-as-args'
            else:
                command += f' --feed-as-stdin'
            tasks.append(
                {
                    "command": command,
                    "test_id": i,
                }
            )

        with open(task_path, 'w') as f:
            json.dump(tasks, f, indent=4)
