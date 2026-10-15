from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name='crm_sandbox',
    version='0.1.0',
    description="CRMArena",
    packages=find_packages(),
    install_requires=requirements
)