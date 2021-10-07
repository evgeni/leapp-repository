from leapp.actors import Actor
from leapp.libraries.common import satelliteutils
from leapp.models import SatelliteFacts
from leapp.tags import IPUWorkflowTag, PreparationPhaseTag


class SatellitePrepare(Actor):
    """
    Handle migration of the PostgreSQL legacy-actions files.
    RPM cannot handle replacement of directories by symlinks by default
    without the %pretrans scriptlet. As PostgreSQL package is packaged wrong,
    we have to workround that by migration of the PostgreSQL files
    before the rpm transaction is processed.
    """

    name = 'satellite_prepare'
    consumes = (SatelliteFacts, )
    produces = ()
    tags = (IPUWorkflowTag, PreparationPhaseTag)

    def process(self):
        facts = next(self.consume(SatelliteFacts), None)
        if not facts or not facts.has_foreman:
            return

        satelliteutils.apply_postgresql_workaround()
