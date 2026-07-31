#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file compare.py
@brief Command for comparing files in cli-test-framework
@author Xiaotong Wang
@date 2024
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from ..file_comparator.factory import ComparatorFactory
from ..file_comparator.result import ComparisonResult

logger = logging.getLogger("cli_test_framework.commands.compare")


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Compare two files.")
    parser.add_argument("file1", help="Path to the first file")
    parser.add_argument("file2", help="Path to the second file")
    parser.add_argument("--start-line", type=int, default=1, help="Starting line number (1-based)")
    parser.add_argument("--end-line", type=int, help="Ending line number (1-based)")
    parser.add_argument("--start-column", type=int, default=1, help="Starting column number (1-based)")
    parser.add_argument("--end-column", type=int, help="Ending column number (1-based)")
    parser.add_argument("--file-type", help="Type of the files to compare", default="auto")
    parser.add_argument("--encoding", default="utf-8", help="File encoding for text files")
    parser.add_argument("--chunk-size", type=int, default=8192, help="Chunk size for binary comparison")
    parser.add_argument("--output-format", choices=["text", "json", "html"], default="text",
                        help="Output format for the comparison result")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with detailed logging")
    parser.add_argument("--similarity", action="store_true",
                        help="When comparing binary files, compute and show similarity index")
    parser.add_argument("--num-threads", type=int, default=4, help="Number of threads for parallel processing")
    
    # CSV comparison options
    csv_group = parser.add_argument_group('CSV comparison options')
    csv_group.add_argument("--csv-rtol", type=float, default=1e-5,
                         help="Relative tolerance for numerical comparison in CSV files")
    csv_group.add_argument("--csv-atol", type=float, default=1e-8,
                         help="Absolute tolerance for numerical comparison in CSV files")
    csv_group.add_argument("--csv-delimiter", default=",",
                         help="CSV field delimiter (default: comma)")
    csv_group.add_argument("--csv-quotechar", default='"',
                         help="Character used for quoting fields in CSV (default: double quote)")
    csv_group.add_argument("--csv-data-filter", type=str,
                         help="Data filter to apply before comparison. "
                              "Example: '>1e-6', '<=0.01', 'abs>1e-9'. "
                              "Filters out numeric cells that do not meet the criteria "
                              "from BOTH files before comparison.")

    # JSON comparison options
    json_group = parser.add_argument_group('JSON comparison options')
    json_group.add_argument("--json-compare-mode", choices=["exact", "key-based"], default="exact",
                      help="JSON comparison mode: exact (default) or key-based")
    json_group.add_argument("--json-key-field", help="Key field(s) to use for key-based JSON comparison")
    
    # H5 comparison options
    h5_group = parser.add_argument_group('HDF5 comparison options')
    h5_group.add_argument("--h5-table", help="Comma-separated list of table names to compare in HDF5 files")
    h5_group.add_argument("--h5-table-regex", help="Comma-separated list of regular expression patterns to match table names in HDF5 files. Each pattern is matched independently.")
    h5_group.add_argument("--h5-structure-only", action="store_true", 
                         help="Only compare HDF5 file structure without comparing content")
    h5_group.add_argument("--h5-show-content-diff", action="store_true",
                         help="Show detailed content differences when content differs")
    h5_group.add_argument("--h5-rtol", type=float, default=1e-5,
                         help="Relative tolerance for numerical comparison in HDF5 files")
    h5_group.add_argument("--h5-atol", type=float, default=1e-8,
                         help="Absolute tolerance for numerical comparison in HDF5 files")
    h5_group.add_argument("--h5-data-filter", type=str,
                         help="Data filter to apply before comparison. "
                              "Example: '>1e-6', '<=0.01', 'abs>1e-9'. "
                              "Filters out data that does not meet the criteria from BOTH files before comparison.")
    h5_group.add_argument("--h5-no-expand-path", dest="h5_expand_path", action="store_false",
                         help="Do not expand HDF5 group paths to compare all sub-items.")
    
    return parser.parse_args()

def detect_file_type(file_path):
    """Detect the type of file based on its extension"""
    ext = Path(file_path).suffix.lower()
    if ext == '.json':
        return 'json'
    elif ext == '.xml':
        return 'xml'
    elif ext in ['.h5', '.hdf5']:
        return 'h5'
    elif ext == '.csv':
        return 'csv'
    elif ext in ['.txt', '.py', '.md', '.html', '.css', '.js']:
        return 'text'
    else:
        return 'binary'

def format_result(result, output_format):
    """Format the comparison result according to the specified output format"""
    if output_format == "json":
        return result.to_json()
    elif output_format == "html":
        return result.to_html()
    else:
        return str(result)

def run_comparison(args, logger=None):
    """Execute file comparison from a parsed arguments namespace.

    This function can be called from both the standalone compare-files entry point
    and the cli-test compare subcommand.

    Returns:
        int: Exit code (0 if files are identical, 1 otherwise)
    """
    if logger is None:
        logger = logging.getLogger("cli_test_framework.commands.compare")

    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug mode enabled")

    # Adjust for 0-based indexing
    start_line = max(0, args.start_line - 1)
    end_line = None if args.end_line is None else max(0, args.end_line - 1)
    start_column = max(0, args.start_column - 1)
    end_column = None if args.end_column is None else max(0, args.end_column - 1)

    # Resolve file paths
    file1_path = Path(args.file1).resolve()
    file2_path = Path(args.file2).resolve()

    if not file1_path.exists():
        raise ValueError(f"File not found: {file1_path}")
    if not file2_path.exists():
        raise ValueError(f"File not found: {file2_path}")

    # Determine file type
    file_type = args.file_type
    if file_type == "auto":
        file_type = detect_file_type(file1_path)
        logger.info(f"Auto-detected file type: {file_type}")

    # Prepare comparator kwargs
    comparator_kwargs = {
        "encoding": args.encoding,
        "chunk_size": args.chunk_size,
        "verbose": args.verbose or args.debug,
        "num_threads": args.num_threads
    }
    
    # Add file type specific arguments
    if file_type == "json":
        comparator_kwargs["compare_mode"] = args.json_compare_mode
        if args.json_key_field:
            key_fields = [field.strip() for field in args.json_key_field.split(',')]
            comparator_kwargs["key_field"] = key_fields[0] if len(key_fields) == 1 else key_fields
    
    if file_type == "csv":
        comparator_kwargs["rtol"] = args.csv_rtol
        comparator_kwargs["atol"] = args.csv_atol
        comparator_kwargs["delimiter"] = args.csv_delimiter
        comparator_kwargs["quotechar"] = args.csv_quotechar
        if args.csv_data_filter:
            comparator_kwargs["data_filter"] = args.csv_data_filter

    if file_type == "h5":
        if args.h5_table:
            tables = [table.strip() for table in args.h5_table.split(',')]
            comparator_kwargs["tables"] = tables
        if args.h5_table_regex:
            comparator_kwargs["table_regex"] = args.h5_table_regex
        comparator_kwargs["structure_only"] = args.h5_structure_only
        comparator_kwargs["show_content_diff"] = args.h5_show_content_diff
        comparator_kwargs["rtol"] = args.h5_rtol
        comparator_kwargs["atol"] = args.h5_atol
        if args.h5_data_filter:
            comparator_kwargs["data_filter"] = args.h5_data_filter
        comparator_kwargs["expand_path"] = args.h5_expand_path
    
    if file_type == "binary":
        comparator_kwargs["similarity"] = args.similarity

    # Create comparator and perform comparison
    comparator = ComparatorFactory.create_comparator(file_type, **comparator_kwargs)
    result = comparator.compare_files(
        file1_path,
        file2_path,
        start_line,
        end_line,
        start_column,
        end_column
    )

    # Output result
    output = format_result(result, args.output_format)
    print(output)

    return 0 if result.identical else 1


def main():
    """Main entry point for the compare-files command"""
    try:
        args = parse_arguments()
        exit_code = run_comparison(args)
        sys.exit(exit_code)

    except ValueError as ve:
        logger.error(f"ValueError: {ve}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"An unexpected error occurred")
        sys.exit(1)


if __name__ == "__main__":
    main()
