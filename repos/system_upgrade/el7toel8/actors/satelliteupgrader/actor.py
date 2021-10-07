from leapp.actors import Actor
from leapp.libraries.stdlib import run
from leapp.models import SatelliteFacts
from leapp.tags import FirstBootPhaseTag, IPUWorkflowTag


class SatelliteUpgrader(Actor):
    """
    Execute installer in the freshly booted system, to finalize Satellite configuration
    """

    name = 'satellite_upgrader'
    consumes = (SatelliteFacts, )
    produces = ()
    tags = (IPUWorkflowTag, FirstBootPhaseTag)

    def process(self):
        facts = next(self.consume(SatelliteFacts), None)
        if not facts or not facts.has_foreman:
            return

        run(['foreman-installer'])  # upstream-name
