from setuptools import setup, find_packages

setup(
    name="renaissance-weekly",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "sendgrid>=6.0.0",
        "aiohttp>=3.8.0",
        "aiofiles>=0.8.0",
        "feedparser>=6.0.0",
        "pydub>=0.25.0",
        "beautifulsoup4>=4.11.0",
        "python-dotenv>=0.19.0",
        "requests>=2.28.0",
        "python-dateutil>=2.8.0",
    ],
    entry_points={
        "console_scripts": [
            "renaissance-weekly=main:main",
        ],
    },
    python_requires=">=3.8",
)