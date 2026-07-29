from setuptools import setup, find_packages
import os

# Read the contents of the README file
this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="cli-test-framework",
    version="1.2.1",
    author="Xiaotong Wang",
    author_email="xiaotongwang98@gmail.com",
    description="A powerful command line testing framework in Python with setup modules, parallel execution, and file comparison capabilities.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ozil111/cli-test-framework",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "dukpy==0.5.0",
        "h5py>=3.11.0,<4.0.0",
        "numpy>=1.21.0; python_version<'3.12'",
        "numpy>=1.26.0; python_version>='3.12'",
        "setuptools>=75.8.0",
        "wheel>=0.45.1"
    ],
    extras_require={
        "tui": ["textual>=0.40.0"],
    },
    entry_points={
        'console_scripts': [
            'cli-test=cli_test_framework.cli:main',
            'compare-files=cli_test_framework.commands.compare:main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires='>=3.9',
    project_urls={
        'Documentation': 'https://github.com/ozil111/cli-test-framework/blob/main/docs/user_manual.md',
        'Source': 'https://github.com/ozil111/cli-test-framework',
        'Tracker': 'https://github.com/ozil111/cli-test-framework/issues',
    },
)
