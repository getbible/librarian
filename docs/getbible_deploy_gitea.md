# Guide to Building and Deploying a GetBible Package to Our Gitea's PyPI Package Registry

This guide focuses on building your Python package and deploying it to your Gitea system's PyPI package registry. The provided documentation gives a clear outline of the requirements and steps needed.

## Prerequisites

- Python and necessary build tools installed.
- `pip` for package installation.
- `twine` for package uploading.

## Step 1: Building the Python Package

### 1.1 Create a Source Distribution

Navigate to your package directory and run:

```bash
python setup.py sdist
```

This creates a source distribution in the `dist/` folder.

### 1.2 Create a Wheel Distribution

For a wheel (`.whl`) distribution:

```bash
python setup.py bdist_wheel
```

This places a wheel file in the `dist/` folder.

## Step 2: Configuring the Package Registry

### 2.1 Edit `~/.pypirc`

Add the following to your `~/.pypirc` file:

```ini
[distutils]
index-servers = getbible

[getbible]
repository = https://git.vdm.dev/api/packages/getbible/pypi
username = {username}
password = {token}
```

Replace `{owner}`, `{username}`, and `{token}` with your Gitea details.

For more information on the PyPI registry, [see the documentation](https://docs.gitea.com/usage/packages/pypi/).

## Step 3: Publish the Package

### 3.1 Upload Package

Run the following command to upload your package:

```bash
python3 -m twine upload --repository getbible dist/*
```

This uploads all files in the `dist/` directory (`.tar.gz` and `.whl`).

**Note:** You cannot publish a package if a package of the same name and version already exists.

## Step 4: Install the Package

### 4.1 Install Using pip

To install a package from the Gitea package registry:

```bash
pip install --index-url https://git.vdm.dev/api/packages/getBible/pypi/simple/ getBible-librarian
```

## Conclusion

You now have a straightforward process for building and deploying a Python package to your Gitea system's PyPI package registry. This setup ensures a seamless workflow for managing and distributing Python packages within your organization or for personal use.
