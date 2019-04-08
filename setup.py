#!/usr/bin/env python
# encoding=utf-8
import os
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.md')).read()

setup(name='almar',
      version='0.7.6',  # Use bumpversio to update
      description='Search and replace for subject fields in Alma records.',
      long_description=README,
      long_description_content_type='text/markdown',
      classifiers=[
          'Programming Language :: Python',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: 3.7',
      ],
      keywords='marc alma',
      author='Dan Michael O. Heggø',
      author_email='d.m.heggo@ub.uio.no',
      url='https://github.com/scriptotek/almar',
      license='MIT',
      install_requires=['six',
                        'requests',
                        'tqdm',
                        'prompter',
                        'pyyaml',
                        'colorama',
                        'coloredlogs',
                        'raven',
                        'vkbeautify',
                        'lxml',
                        'questionary',
                        ],
      setup_requires=['pytest-runner'],
      tests_require=['pytest', 'pytest-pycodestyle', 'pytest-cov', 'responses', 'mock'],
      entry_points={'console_scripts': ['almar=almar.almar:main']},
      options={
          'build_scripts': {
              'executable': '/usr/bin/env python',
          },
      },
      packages=['almar']
      # data_files=[(AppDirs('Lokar').user_config_dir, ['almar.cfg'])]
      )
