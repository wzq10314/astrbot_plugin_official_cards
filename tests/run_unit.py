"""Run the standalone contracts; integrations require other repositories."""
from pathlib import Path
import sys, unittest
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root.parent.parent))
integration = {"test_cross_review", "test_gok_help_actions", "test_resource_menus", "test_sky_menu", "test_text_help_images"}
names = [p.stem for p in sorted(root.glob("test_*.py")) if p.stem not in integration]
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in names)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
