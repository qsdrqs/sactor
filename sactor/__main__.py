import argparse
import sys
import os

from sactor import Sactor
from sactor.test_generator import ExecutableTestGenerator, TestGeneratorResult
from sactor.test_runner import ExecutableTestRunner, TestRunnerResult


def parse_translate(parser):
    parser.add_argument(
        'input_file',
        type=str,
        help='The input C file to translate to Rust'
    )

    parser.add_argument(
        'test_command_path',
        help='The path to the json file containing the test commands, need to follow the format specified in the README'
    )

    parser.add_argument(
        '--type',
        choices=['bin', 'lib'],
        required=True,
        help='Whether the target is a binary program or a library'
    )

    parser.add_argument(
        '--config',
        '-c',
        type=str,
        dest='config_file',
        help='The configuration file to use'
    )

    parser.add_argument(
        '--build-dir',
        '-b',
        type=str,
        help='The directory to use for the build process'
    )

    parser.add_argument(
        '--result-dir',
        '-r',
        type=str,
        help='The directory to use for the result process'
    )

    parser.add_argument(
        '--llm-stat',
        '-l',
        type=str,
        help='The path to output the LLM statistics json file, default to {result_dir}/llm_stat.json'
    )

    parser.add_argument(
        '--no-verify',
        action='store_true',
        help='Do not verify the generated Rust code'
    )

    parser.add_argument(
        '--unidiomatic-only',
        action='store_true',
        help='Only translate C code into unidiomatic Rust code, skipping the idiomatic translation'
    )

    parser.add_argument(
        '--extra-compile-command',
        type=str,
        help='The extra compile command to use to compile the C code', # TODO: dirty implement, remove this later
    )

    parser.add_argument(
        '--executable-object',
        '-e',
        type=str,
        default=None,
        help='The path to the executable object file, required and only required for library targets'
    )



def parse_run_tests(parser):
    parser.add_argument(
        'test_samples_path',
        type=str,
        help='The path to the test samples output json file'
    )

    parser.add_argument(
        'target',
        help='The target program or library to test'
    )

    parser.add_argument(
        'test_sample_number',
        type=int,
        help='The number (relative to 0) of the test sample to run'
    )

    parser.add_argument(
        '--type',
        choices=['bin', 'lib'],
        required=True,
        help='Whether the target is a binary program or a library'
    )

    parser.add_argument(
        '--config',
        '-c',
        type=str,
        dest='config_file',
        help='The configuration file to use'
    )

    parser.add_argument(
        "--feed-as-args",
        action='store_true',
        default=None,
        help='Only avaliable for binary targets. If set, the test samples will be fed as arguments to the target program. Default set this unless --feed-as-stdin is set.'
    )

    parser.add_argument(
        "--feed-as-stdin",
        action='store_true',
        default=None,
        help='Only avaliable for binary targets. If set, the test samples will be fed to the target program via stdin.'
    )


def parse_generate_tests(parser):
    parser.add_argument(
        'input_file',
        type=str,
        help='The input C file to generate tests for'
    )

    parser.add_argument(
        'count',
        type=int,
        help='The number of total test samples expected. This will include the test samples provided in the test_samples_path'
    )

    parser.add_argument(
        '--out-test-sample-path',
        '-os',
        type=str,
        help='The path to the test samples output json file, default to `$PWD/test_task/test_samples.json`'
    )

    parser.add_argument(
        '--out-test-task-path',
        '-ot',
        type=str,
        help='The path to the test task output json file, default to `$PWD/test_task/test_task.json`'
    )

    parser.add_argument(
        '--type',
        choices=['bin', 'lib'],
        required=True,
        help='Whether the target is a binary program or a library'
    )

    parser.add_argument(
        '--config',
        '-c',
        type=str,
        dest='config_file',
        help='The configuration file to use'
    )

    parser.add_argument(
        '--test-samples_path',
        '-s',
        type=str,
        help='The path to the test samples output json file, if any, need to follow the format specified in the README'
    )

    parser.add_argument(
        '--input-document',
        '-i',
        type=str,
        help='The path to the input document file, if any'
    )

    parser.add_argument(
        '--timeout',
        '-t',
        type=int,
        default=60,
        help='The execution timeout in seconds for each test'
    )

    parser.add_argument(
        '--executable',
        '-e',
        type=str,
        default=None,
        help='The path to the executable to test, only required for binary targets. If not set, sactor will try to directly compile the input file'
    )

    parser.add_argument(
        "--feed-as-args",
        action='store_true',
        default=None,
        help='Only avaliable for binary targets. If set, the test samples will be fed as arguments to the target program. Default set this unless --feed-as-stdin is set.'
    )

    parser.add_argument(
        "--feed-as-stdin",
        action='store_true',
        default=None,
        help='Only avaliable for binary targets. If set, the test samples will be fed to the target program via stdin.'
    )


def translate(parser, args):
    is_executable = args.type == 'bin'
    if not is_executable:
        if args.executable_object is None:
            parser.error('Executable object must be provided for library targets')

    sactor = Sactor(
        input_file=args.input_file,
        test_cmd_path=args.test_command_path,
        build_dir=args.build_dir,
        result_dir=args.result_dir,
        config_file=args.config_file,
        no_verify=args.no_verify,
        unidiomatic_only=args.unidiomatic_only,
        llm_stat=args.llm_stat,
        extra_compile_command=args.extra_compile_command,
        is_executable=is_executable,
        executable_object=args.executable_object
    )

    sactor.run()


def run_tests(parser, args):
    if args.type == 'lib':
        if args.feed_as_args is not None:
            parser.error('--feed-as-args is only avaliable for binary targets')
        if args.feed_as_stdin is not None:
            parser.error(
                '--feed-as-stdin is only avaliable for binary targets')

    if args.type == 'bin':
        if args.feed_as_args is None and args.feed_as_stdin is None:
            args.feed_as_args = True
        if args.feed_as_args and args.feed_as_stdin:
            parser.error(
                'Only one of --feed-as-args and --feed-as-stdin can be set yet')

    if args.feed_as_args:
        feed_as_args = True
    else:
        assert args.feed_as_stdin
        feed_as_args = False

    if args.type == 'bin':
        target = os.path.abspath(args.target)
        test_runner = ExecutableTestRunner(
            args.test_samples_path,
            target,
            config_path=args.config_file,
            feed_as_arguments=feed_as_args
        )
        result = test_runner.run_test(args.test_sample_number)
        if result[0] == TestRunnerResult.PASSED:
            print(f'✅ Test {args.test_sample_number} passed successfully!')
            sys.exit(0)
        else:
            print(f'❌ Test {args.test_sample_number} failed!', file=sys.stderr)
            print('Diff (-actual +expected):', file=sys.stderr)
            print(result[1], file=sys.stderr)
            sys.exit(1)

    elif args.type == 'lib':
        raise NotImplementedError('Library test runner not implemented yet')

    else:
        raise ValueError(f'Invalid type: {args.type}')


def generate_tests(parser, args):
    if args.type == 'lib':
        if args.feed_as_args is not None:
            parser.error('--feed-as-args is only avaliable for binary targets')
        if args.feed_as_stdin is not None:
            parser.error(
                '--feed-as-stdin is only avaliable for binary targets')

    if args.type == 'bin':
        if args.feed_as_args is None and args.feed_as_stdin is None:
            args.feed_as_args = True
        if args.feed_as_args and args.feed_as_stdin:
            parser.error(
                'Only one of --feed-as-args and --feed-as-stdin can be set yet')

    if args.feed_as_args:
        feed_as_args = True
    else:
        assert args.feed_as_stdin
        feed_as_args = False

    if args.out_test_task_path and not args.out_test_task_path.endswith('.json'):
        parser.error('The test task output path should end with .json')

    if args.out_test_sample_path and not args.out_test_sample_path.endswith('.json'):
        parser.error('The test samples output path should end with .json')

    if args.type == 'bin':
        test_generator = ExecutableTestGenerator(
            config_path=args.config_file,
            file_path=args.input_file,
            test_samples=[],  # test samples provided from test_samples_path in command line mode
            test_samples_path=args.test_samples_path,
            executable=args.executable,
            input_document=args.input_document,
            feed_as_arguments=feed_as_args,
        )

        result = test_generator.generate_tests(args.count)
        if result == TestGeneratorResult.SUCCESS:
            print('✅ Tests generated successfully!')
            test_generator.create_test_task(
                args.out_test_task_path,
                args.out_test_sample_path
            )
            sys.exit(0)
        else:
            print('❌ Failed to generate tests')
            sys.exit(1)
    elif args.type == 'lib':
        raise NotImplementedError('Library test runner not implemented yet')

    else:
        raise ValueError(f'Invalid type: {args.type}')


def main():
    parser = argparse.ArgumentParser(
        description='SACToR: Structure-Aware C To Rust Translator'
    )

    subparsers = parser.add_subparsers(
        dest='subcommand',
        description='valid subcommands for SACToR to work in different modes',
        help='Use one of these subcommands followed by -h for additional help',
        required=True
    )

    translate_parser = subparsers.add_parser(
        'translate',
        help='Translate C code into Rust code'
    )

    test_runner_parser = subparsers.add_parser(
        'run-tests',
        help='Run tests on the target program or library'
    )

    generate_tests_parser = subparsers.add_parser(
        'generate-tests',
        help='Generate tests for the target program or library'
    )

    parse_translate(translate_parser)
    parse_run_tests(test_runner_parser)
    parse_generate_tests(generate_tests_parser)

    args = parser.parse_args()

    match args.subcommand:
        case 'translate':
            translate(parser, args)
        case 'run-tests':
            run_tests(parser, args)
        case 'generate-tests':
            generate_tests(parser, args)
        case _:
            parser.print_help()


if __name__ == '__main__':
    main()
