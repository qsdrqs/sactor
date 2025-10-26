import json
import os
import shutil
import subprocess
from typing import override

from sactor import logging as sactor_logging
from sactor import utils
from sactor.llm import llm_factory

from .test_generator import TestGenerator
from .test_generator_types import TestGeneratorResult


logger = sactor_logging.get_logger(__name__)


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
            executable = utils.compile_c_code(file_path)

        executable = os.path.abspath(executable) # get the absolute path
        self.executable = executable

        for sample in self.init_test_samples:
            self._execute_test_sample(sample)

    def _execute_test_sample(self, test_sample):
        # TODO: support error tests
        tmp_dir = f'{utils.get_temp_dir()}/exec_test'
        os.makedirs(tmp_dir, exist_ok=True)
        try:
            if self.feed_as_arguments:
                feed_input_str = f'{self.executable} {test_sample}'
                cmd = feed_input_str.split()
                result = utils.run_command(
                    self.valgrind_cmd + cmd,
                    timeout=self.timeout_seconds,
                    cwd=tmp_dir,
                )
            else:
                cmd = self.executable
                result = utils.run_command(
                    self.valgrind_cmd + [cmd],
                    timeout=self.timeout_seconds,
                    cwd=tmp_dir,
                    input_data=f"{test_sample}\n",
                )
            if result.returncode != 0:
                raise ValueError(
                    f"Failed to run the executable with the input: {result.stdout + result.stderr}"
                )
        except subprocess.TimeoutExpired as e:
            logger.error("Timeout while executing sample: %s", e)
            raise ValueError(f"Timeout: {e}. Please check the input format.")

        # Rerun without valgrind
        if self.feed_as_arguments:
            feed_input_str = f'{self.executable} {test_sample}'
            cmd = feed_input_str.split()
            result = utils.run_command(
                cmd,
                timeout=self.timeout_seconds,
                cwd=tmp_dir,
            )
        else:
            cmd = self.executable
            result = utils.run_command(
                cmd,
                timeout=self.timeout_seconds,
                cwd=tmp_dir,
                input_data=f"{test_sample}\n",
            )
        assert result.returncode == 0 # should not fail
        # clean up tmp dir
        shutil.rmtree(tmp_dir)
        return utils.normalize_string(result.stdout + result.stderr)

    def _generate_test_impl(
        self,
        count,
        counter_examples=None,
        feedback=None,
        attempt=0,
    ) -> TestGeneratorResult:
        if count < 0:
            raise ValueError(f"Invalid count: {count}")

        if count == 0:
            # don't need to generate any test cases
            return TestGeneratorResult.SUCCESS

        if attempt >= self.max_attempts:
            logger.error("Max attempts exceeded: %d", attempt)
            return TestGeneratorResult.MAX_ATTEMPTS_EXCEEDED

        # Generate test cases
        prompt = ''
        system_message = "You are an expert to write end-to-end tests for a C program." # TODO: config it

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

        if feedback:
            prompt += f'''
Lastly, some test cases are invalid:
```
{feedback}
```
Check the error message and provide valid test cases.
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
        if self.feed_as_arguments:
            prompt += f'''
**NOTE**: The C program is executed with the following command:
```
/path/to/prog <input>
```
Your input will directly feed to the program as an argument. Don't provide program name in the input.
'''

        result = self.llm.query(prompt, override_system_message=system_message)
        success_count = 0
        for i in range(1, count + 1):
            try:
                test_case = utils.parse_llm_result(result, f"input {i}")
                init_count = len(self.test_samples)
                self.test_samples.add(test_case[f"input {i}"].strip())
                if len(self.test_samples) == init_count + 1:
                    success_count += 1 # add distinct test case
            except ValueError as _:
                error_message = f'''Failed to parse the input {i}. Please provide input in the correct format.
----INPUT i----
```
Your input i here
```
----END INPUT i----
REMEMBER: i should start from 1.
'''
                logger.error("%s", error_message)
                return self._generate_test_impl(
                    count - success_count,
                    feedback=error_message,
                    attempt=attempt+1
                )  # Retry

        if success_count < count:
            logger.info(
                "Generated %d test cases, required %d", success_count, count
            )
            return self._generate_test_impl(count - success_count, attempt=attempt+1)

        # collect test cases
        counter_examples = []
        remaining_test_samples = set()
        for i, sample in enumerate(self.test_samples):
            try:
                output = self._execute_test_sample(sample)
            except ValueError as e:
                counter_examples.append((sample, e))
                continue
            logger.info("Test %d verified", i)
            self.test_samples_output.append(
                {
                    "input": sample,
                    "output": output,
                }
            )
            remaining_test_samples.add(sample.strip())

        self.test_samples = set(remaining_test_samples)
        if len(counter_examples) > 0:
            # remove invalid test cases
            logger.info("Counter examples: %d", len(counter_examples))
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
