import textwrap

from leapp import reporting
from leapp.actors import Actor
from leapp.libraries.actor.satelliteupgradecheck import satelliteupgradecheck
from leapp.models import Report, SatelliteFacts
from leapp.tags import ChecksPhaseTag, IPUWorkflowTag


class SatelliteUpgradeCheck(Actor):
    """
    Check state of Satellite system before upgrade
    """

    name = 'satelliteupgradecheck'
    consumes = (SatelliteFacts,)
    produces = (Report,)
    tags = (IPUWorkflowTag, ChecksPhaseTag)

    def process(self):
        facts = next(self.consume(SatelliteFacts), None)
        if not facts or not facts.has_foreman:
            return

        satelliteupgradecheck(facts)
