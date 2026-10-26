# setup.py for a general package
#
# Direct install (all systems):
#   "python setup.py install"
#
# For Python 3.x use the corresponding Python executable,
# e.g. "python3 setup.py ..."
#
# Install using pip:
#   "pip install -e ."
#
# (C) 2015-2017 David Toro <davsamirtor@gmail.com>
#
import sys
import io
import os
import re
from glob import glob


def parse_requirements(filename):
    """ load requirements from a pip requirements file """
    # https://github.com/capless/warrant/issues/96
    lineiter = (line.strip() for line in open(filename))
    return [line for line in lineiter if line and not line.startswith("#")]

try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup, find_packages


def read(*names, **kwargs):
    """Python 2 and Python 3 compatible text file reading.
    Required for single-sourcing the version string.
    """
    with io.open(
        os.path.join(os.path.dirname(__file__), *names),
        encoding=kwargs.get("encoding", "utf8")
    ) as fp:
        return fp.read()


def find_version(*file_paths):
    """
    Search the file for a version string.
    file_path contain string path components.
    Reads the supplied Python module as text without importing it.
    """
    version_file = read(*file_paths)
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                              version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")

# information of package
print(sys.version) # version of python

here = os.path.abspath(os.path.dirname(__file__))
init_file = '__init__.py'
package = ""
here, pkg_lst, files_list = next(os.walk(here))
script_list = [i for i in files_list if i.endswith(".py") and i != "setup.py"]
for pkg in pkg_lst:
    _, _, files = next(os.walk(os.path.join(here, pkg)))
    if init_file in files:
        package = pkg
        break

if not package:
    raise TypeError("no package found")

try:
    version = find_version(package, init_file)
    # print package version
    print("package '{}' is in version {}".format(package, version))
except RuntimeError:
    version = "0.0.1"
    print("package '{}' has no version".format(package))  # no version

packages = find_packages(exclude=[])
print("Packages to include {}".format(packages))  # package includes

# Get the long description from the README file
long_description = ""
readmes = glob(os.path.join(here, 'README*'))+glob(os.path.join(here, 'readme*'))
for f_name in readmes:
    long_description += read(f_name) + "\n\n"

install_requires = []
for f_name in glob(os.path.join(here, 'requirements*')):
    install_requires.extend(parse_requirements(f_name))

setup(
    name=package,
    description="Install {}".format(package),
    version=version,
    author='David Toro',
    author_email="davsamirtor@gmail.com",
    url="https://github.com/davtoh/InteligentTracker",
    packages=packages,
    license="GPL v3",
    long_description=long_description,
    # see complete list https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: Education',
        'Intended Audience :: Science/Research',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Natural Language :: English',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Microsoft :: Windows',
        #'Operating System :: MacOS :: MacOS X',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Education',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    keywords='tracker object face color shape recognition scenes visual world',
    platforms='any',
    install_requires=install_requires,
    scripts=script_list,
)
