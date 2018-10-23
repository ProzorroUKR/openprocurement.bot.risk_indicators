from setuptools import setup, find_packages

version = '1.0.2'

requires = [
    'PyYAML',
    'gevent',
    'requests',
    'setuptools',
]

test_requires = requires + [
    'mock',
    'webtest',
    'python-coveralls',
]

entry_points = {
    'console_scripts': [
        'risk_indicator_bot = openprocurement.bot.risk_indicators.main:main'
    ]
}

setup(name='openprocurement.bot.risk_indicators',
      version=version,
      description="",
      long_description=open("README.rst").read(),
      classifiers=[
        "Programming Language :: Python",
      ],
      keywords="web services",
      author='RaccoonGang',
      author_email='info@raccoongang.com',
      license='Apache License 2.0',
      url='https://github.com/ProzorroUKR/openprocurement.bot.risk_indicators',
      packages=find_packages(exclude=['ez_setup']),
      namespace_packages=['openprocurement', 'openprocurement.bot'],
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=test_requires,
      extras_require={'test': test_requires},
      entry_points=entry_points,
      )
