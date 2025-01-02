import argparse
import sys

from .executable_test_runner import ExecutableTestRunner
from .test_runner_types import TestRunnerResult


def main():
    parser = argparse.ArgumentParser(
        description='Sactor test runner: Run a test sample on a target program or library'
    )

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
        help='The type of the target program/library'
    )

    parser.add_argument(
        "--feed-as-args",  # Note the name change
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

    args = parser.parse_args()

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
        test_runner = ExecutableTestRunner(
            args.test_samples_path,
            args.target,
            feed_as_arguments=feed_as_args
        )
        result = test_runner.run_test(args.test_sample_number)
        if result[0] == TestRunnerResult.PASSED:
            print(f'✅ Test {args.test_sample_number} passed successfully!')
            sys.exit(0)
        else:
            print(f'❌ Test {args.test_sample_number} failed!')
            print(result[1])
            sys.exit(1)

    elif args.type == 'lib':
        raise NotImplementedError('Library test runner not implemented yet')

    else:
        raise ValueError(f'Invalid type: {args.type}')


if __name__ == '__main__':
    main()
