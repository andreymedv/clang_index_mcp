#!/usr/bin/env python3
"""
Setup script for C++ MCP Server
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

# Read requirements
requirements = (this_directory / "requirements.txt").read_text(encoding="utf-8").splitlines()
requirements = [r.strip() for r in requirements if r.strip() and not r.startswith("#")]

setup(
    name="clang-index-mcp",
    version="0.1.0",
    author="C++ MCP Server Contributors",
    description="An MCP (Model Context Protocol) server for analyzing C++ codebases using libclang",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/andreymedv/clang_index_mcp",
    packages=find_packages(exclude=["tests", "scripts"]),
    install_requires=requirements,
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Software Development :: Code Generators",
    ],
    keywords="mcp model-context-protocol c++ cpp clang libclang code-analysis",
    entry_points={
        "console_scripts": [
            "clang-index-mcp=mcp_server.cpp_mcp_server:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.json"],
    },
    zip_safe=False,
)
