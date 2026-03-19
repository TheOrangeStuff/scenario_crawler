"""Entry point: python -m Python_Version [path/to/data.mat]"""

import sys
from .profiler_analyzer import ProfilerAnalyzer

mat_file = sys.argv[1] if len(sys.argv) > 1 else None
ProfilerAnalyzer(mat_file)
