"""Registro dos preenchedores de formulario."""

from __future__ import annotations

from automatic_candidate.appliers.base import Applier, ApplyContext
from automatic_candidate.appliers.generic_form import GenericFormApplier
from automatic_candidate.appliers.portals import (
    GreenhouseApplier,
    GupyApplier,
    LeverApplier,
    WorkdayApplier,
)

APPLIERS: dict[str, type[Applier]] = {
    cls.name: cls
    for cls in (
        GenericFormApplier,
        GreenhouseApplier,
        LeverApplier,
        WorkdayApplier,
        GupyApplier,
    )
}


def build_applier(name: str, context: ApplyContext) -> Applier:
    applier_cls = APPLIERS.get((name or "generic").lower(), GenericFormApplier)
    return applier_cls(context)


__all__ = ["APPLIERS", "Applier", "ApplyContext", "build_applier", "GenericFormApplier"]
