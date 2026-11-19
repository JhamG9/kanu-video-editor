"""Servicios de larga vida compartidos por la API (una instancia por proceso)."""
from kanu.services.batches import BatchRunner
from kanu.services.export import Exporter

exporter = Exporter(workers=2)
runner = BatchRunner(exporter)
