# Intelligent Tracker Documentation Build Instructions

# Build HTML documentation (modern Sphinx):
python -m sphinx -W --keep-going documentation/ documentation/_build/html/

# Or using Makefile / make.bat:
make html

# Open built documentation in browser:
open documentation/_build/html/index.html   # macOS
xdg-open documentation/_build/html/index.html  # Linux
start documentation\_build\html\index.html     # Windows
