import os
import re
import json
from datetime import date

def search_html_files(patterns, directory, output_file):
    """
    Searches HTML files recursively within a directory for a given pattern.

    Args:
        pattern (str): The regular expression pattern to search for.
        directory (str): The directory to search recursively.
        output_file (str): The path to the output text file.
    """

    with open(output_file, 'w') as outfile:
        for root, _, files in os.walk(directory):
            for filename in files:
                if filename.endswith('.html'):
                    file_path = os.path.join(root, filename)

                    results = []
                    try:
                        with open(file_path, 'r') as infile:
                            line_num = 1
                            for line in infile:
                                for pattern, modified_pattern in patterns:
                                    for match in re.finditer(modified_pattern, line):
                                        start, end = match.span()
                                        excerpt = line[start:end].strip()
                                        results.append(f"Line {line_num}: {excerpt} (Pattern: {pattern})")
                                    line_num += 1
                    except FileNotFoundError:
                        outfile.write(f"File not found: {file_path}\n")

                    if results:
                        file_full_path = os.path.join(root, filename).replace(replace_path, '')
                        outfile.write(f"\n** {file_full_path} **\n")
                        outfile.write('\n'.join(results) + '\n')

if __name__ == '__main__':
    today = date.today()

    with open("config.json", 'r') as config_handle:
        config = json.load(config_handle)

    patterns = config['patterns']

    negative_lookahead = r'(?![!?-])'
    merged_patterns = [
        (pattern, re.escape(pattern) + negative_lookahead) if pattern.startswith('<') else (pattern, re.escape(pattern))
        for pattern in patterns
    ]

    for application in config['application_repo']:
        directory = application['source_path']
        replace_path = application['replace_path']
        report_name = application['report_name']
        output_file = f"Reports/{report_name}-{today.strftime("%m-%d-%Y")}.txt"

        print(f"Searching patterns in: {directory}")
        search_html_files(merged_patterns, directory, output_file)
        print(f"Search results written to: {output_file}")

    print("Search completed for all applications.")
