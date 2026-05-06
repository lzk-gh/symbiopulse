from setuptools import setup, find_packages

setup(
    name="symbiopulse",
    version="0.1.11",
    author="SymbioPath Contributors",
    author_email="maintainers@symbiopulse.io",
    description="Code context manager with evolutionary instinct for AI agents",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/symbiopulse/symbiopulse",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "litellm>=1.0.0",
        "filelock>=3.12.0",
        "pathspec>=0.11.0",
        "mcp>=1.0.0"
    ],
    entry_points={
        "console_scripts": [
            "sym-mcp=symbiopulse.interfaces.mcp_server:run"
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Intended Audience :: Developers",
    ],
    python_requires=">=3.8",
)
