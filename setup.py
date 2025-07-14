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
    extras_require={
        "test": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "pytest-timeout>=2.1.0",
            "pytest-mock>=3.10.0",
            "pytest-xdist>=3.0.0",
            "pytest-watch>=4.2.0",
            "responses>=0.22.0",
            "faker>=18.0.0",
            "aioresponses>=0.7.4",
        ],
        "dev": [
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
            "isort>=5.12.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "renaissance-weekly=main:main",
        ],
    },
    python_requires=">=3.8",
)