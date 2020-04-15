import setuptools

setuptools.setup(
    name="sappservice",
    version=0.4,
    url="https://github.com/TurBoss/matrix-spring-appservice",

    author="TurBoss",
    author_email="turboss@mail.comt",

    description="A Python 3 asyncio Matrix SpringRTS appservice.",
    long_description=open("README.md").read(),

    packages=setuptools.find_packages(),

    install_requires=[
        "commonmark",
        "mautrix",
        "matrix_client",
        "sqlalchemy",
        "asyncblink",
        "ruamel.yaml",
        "aiohttp",
        "git+https://github.com/TurBoss/asyncspring.git"

    ],
    extras_require={
    },
    python_requires="~=3.6",

    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: GNU GPL v3",
        "Topic :: Communications :: Chat",
        "Framework :: AsyncIO",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ]
)
