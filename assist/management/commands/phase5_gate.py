from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run Phase 5 gate (scripts.phase5_gate.main)"

    def handle(self, *args, **options):
        from pathlib import Path
        import importlib.util
        import sys

        root = Path(__file__).resolve().parents[3]
        path = root / "scripts" / "phase5_gate.py"
        spec = importlib.util.spec_from_file_location("phase5_gate_mod", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        code = mod.main()
        if code:
            sys.exit(code)
        self.stdout.write(self.style.SUCCESS("PHASE5_GATE_OK"))
