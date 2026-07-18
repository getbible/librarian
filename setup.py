from pathlib import Path

from setuptools import find_packages, setup


long_description = Path("README.md").read_text(encoding="utf-8")

setup(
    name="getbible",
    version="1.2.0",
    author="Llewellyn van der Merwe",
    author_email="getbible@vdm.io",
    description="Retrieve bounded, validated Bible references with ease.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/getbible/librarian",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={"getbible": ["data/*.json"]},
    include_package_data=True,
    install_requires=["requests>=2.32.5,<3"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
)
