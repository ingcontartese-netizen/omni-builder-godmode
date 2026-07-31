"""Four-layer liveness window; fixed timeouts are diagnostic, never truth."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LivenessWindow:
    ui_transport: bool
    session: bool
    workflow: bool
    governed_delivery: bool

    @property
    def state(self) -> str:
        if self.governed_delivery:
            return "GOVERNED_DELIVERY"
        if self.workflow:
            return "WORKFLOW_LIVE_DELIVERY_PENDING"
        if self.session:
            return "SESSION_LIVE_WORKFLOW_UNKNOWN"
        if self.ui_transport:
            return "UI_ONLY"
        return "NO_LIVENESS_EVIDENCE"


def classify(ui_transport: bool, session: bool, workflow: bool, governed_delivery: bool) -> LivenessWindow:
    if governed_delivery and not (workflow and session):
        raise ValueError("DELIVERY_REQUIRES_WORKFLOW_AND_SESSION")
    if workflow and not session:
        raise ValueError("WORKFLOW_REQUIRES_SESSION")
    return LivenessWindow(ui_transport, session, workflow, governed_delivery)
