import importlib.util, os, sys
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_target = os.path.normpath(os.path.join(_root, 'ingest-search/_search_common.py'))
_spec = importlib.util.spec_from_file_location('tools._search_common', _target)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules[__name__] = _mod
