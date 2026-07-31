from setuptools import setup, find_packages
import os
import re

# Read the contents of the README file
this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()


def read_version():
    """Single source of truth: __version__ in symtest/__init__.py."""
    init_path = os.path.join(this_directory, "src", "symtest", "__init__.py")
    with open(init_path, encoding="utf-8") as f:
        match = re.search(r'^__version__ = ["\']([^"\']+)["\']', f.read(), re.MULTILINE)
    if not match:
        raise RuntimeError("Unable to find __version__ in symtest/__init__.py")
    return match.group(1)


setup(
    name="symtest",
    version=read_version(),
    author="Xiaotong Wang",
    author_email="xiaotongwang98@gmail.com",
    description="Regression testing for CLI applications, with multi-step workflows and numerical file comparison.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ozil111/symtest",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "h5py>=3.11.0,<4.0.0",
        "numpy>=1.21.0; python_version<'3.12'",
        "numpy>=1.26.0; python_version>='3.12'",
    ],
    extras_require={
        "yaml": ["PyYAML>=6.0"],
        "tui": ["textual>=0.40.0"],
        "all": [
            "PyYAML>=6.0",
            "textual>=0.40.0",
        ],
        "dev": [
            "PyYAML>=6.0",
            "textual>=0.40.0",
            "pytest>=7.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0",
        ],
    },
    entry_points={
        'console_scripts': [
            'symtest=symtest.cli:main',
            # Backward-compatible alias for users of the old cli-test-framework.
            'cli-test=symtest.cli:main',
            'compare-files=symtest.commands.compare:main',
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
        'Documentation': 'https://github.com/ozil111/symtest/blob/main/docs/user_manual.md',
        'Source': 'https://github.com/ozil111/symtest',
        'Tracker': 'https://github.com/ozil111/symtest/issues',
    },
)
