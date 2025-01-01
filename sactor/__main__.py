import argparse

from sactor import Sactor

def main():
    parser = argparse.ArgumentParser(
        description='SACToR: Structure-Aware C To Rust Translator'
    )

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
        '--config',
        '-c',
        type=str,
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
        '--no-verify',
        action='store_true',
        help='Do not verify the generated Rust code'
    )

    parser.add_argument(
        '--unidiomatic-only',
        action='store_true',
        help='Only translate C code into unidiomatic Rust code, skipping the idiomatic translation'
    )

    args = parser.parse_args()

    sactor = Sactor(
        input_file=args.input_file,
        test_cmd_path=args.test_command_path,
        build_dir=args.build_dir,
        result_dir=args.result_dir,
        config_file=args.config,
        no_verify=args.no_verify,
        unidiomatic_only=args.unidiomatic_only
    )

    sactor.run()

if __name__ == '__main__':
    main()
