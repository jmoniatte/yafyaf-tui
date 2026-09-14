from importlib.metadata import version, PackageNotFoundError

REPOSITORY_URL = "https://github.com/jmoniatte/yafyaf-tui"

try:
    __version__ = version("yafyaf-tui")
except PackageNotFoundError:
    __version__ = "0.0.0"
