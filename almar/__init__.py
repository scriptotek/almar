import pkg_resources  # part of setuptools
from .sru import SruClient
from .alma import Alma
__version__ = pkg_resources.require('almar')[0].version
