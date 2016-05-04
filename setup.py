#!/usr/bin/env python
# encoding=utf-8
import os
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.md')).read()

setup(name='lokar',
      version='0.0.1',
      description='Search and replace for subject fields in Alma records.',
      long_description=README,
      classifiers=[
          'Programming Language :: Python',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3.4',
          'Programming Language :: Python :: 3.5',
      ],
      keywords='marc alma',
      author='Scriptoteket',
      author_email='scriptoteket@ub.uio.no',
      url='https://github.com/scriptotek/lokar',
      license='MIT',
      install_requires=['six',
                        'requests',
                        'appdirs',
                        'tqdm',
                        ],
      setup_requires=['pytest-runner'],
      tests_require=['pytest', 'pytest-pep8', 'pytest-cov', 'responses', 'mock'],
      # entry_points={'console_scripts': ['lokar=lokar:main']},
      py_modules=['lokar']
      # data_files=[(AppDirs('Lokar').user_config_dir, ['lokar.cfg'])]
      )
