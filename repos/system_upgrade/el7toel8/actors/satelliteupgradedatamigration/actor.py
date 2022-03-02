import glob
import os
import shutil

from leapp.actors import Actor
from leapp.models import SatelliteFacts
from leapp.tags import ApplicationsPhaseTag, IPUWorkflowTag

POSTGRESQL_DATA_PATH = '/var/lib/pgsql/data/'
POSTGRESQL_SCL_DATA_PATH = '/var/opt/rh/rh-postgresql12/lib/pgsql/data/'

SYSTEMD_WANTS_BASE = '/etc/systemd/system/multi-user.target.wants/'
SERVICES_TO_DISABLE = ['dynflow-sidekiq@*', 'foreman', 'foreman-proxy',
                       'httpd', 'postgresql', 'pulpcore-api', 'pulpcore-content',
                       'pulpcore-worker@*', 'tomcat']


class SatelliteUpgradeDataMigration(Actor):
    """
    Reconfigure Satellite services and migrate PostgreSQL data
    """

    name = 'satellite_upgrade_data_migration'
    consumes = (SatelliteFacts,)
    produces = ()
    tags = (IPUWorkflowTag, ApplicationsPhaseTag)

    def process(self):
        facts = next(self.consume(SatelliteFacts), None)
        if not facts or not facts.has_foreman:
            return

        # disable services, will be re-enabled by the installer
        for service_name in SERVICES_TO_DISABLE:
            for service in glob.glob(os.path.join(SYSTEMD_WANTS_BASE, '{}.service'.format(service_name))):
                os.unlink(service)

        if facts.postgresql.local_postgresql and os.path.exists(POSTGRESQL_SCL_DATA_PATH):
            # remove empty PostgreSQL data from the package
            if os.path.exists(POSTGRESQL_DATA_PATH):
                os.rmdir(POSTGRESQL_DATA_PATH)
            # move PostgreSQL data to the new home
            shutil.move(POSTGRESQL_SCL_DATA_PATH, POSTGRESQL_DATA_PATH)
