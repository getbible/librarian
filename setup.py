from setuptools import setup, find_packages

with open('requirements.txt') as f:
    required = f.read().splitlines()

setup(
    name="getBible-librarian",
    version="0.2.0",
    author="Llewellyn van der Merwe",
    author_email="getbible@vdm.io",
    description="A Python package to retrieving Bible references with ease.",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="https://git.vdm.dev/getBible/librarian",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={"getbible": ["data/*.json"]},
    include_package_data=True,
    install_requires=required,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)
