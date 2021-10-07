from leapp import reporting
from leapp.libraries.common.testutils import create_report_mocked
from leapp.libraries.actor.satelliteupgradecheck import satelliteupgradecheck
from leapp.snactor.fixture import current_actor_context
from leapp.models import SatelliteFacts, SatellitePostgresqlFacts


def test_old_data(monkeypatch, current_actor_context):
    monkeypatch.setattr(reporting, 'create_report', create_report_mocked())

    satelliteupgradecheck(SatelliteFacts(has_foreman=True, postgresql=SatellitePostgresqlFacts(local_postgresql=True, old_var_lib_pgsql_data=True)))

    assert reporting.create_report.called == 2


def test_no_old_data(monkeypatch, current_actor_context):
    monkeypatch.setattr(reporting, 'create_report', create_report_mocked())

    satelliteupgradecheck(SatelliteFacts(has_foreman=True, postgresql=SatellitePostgresqlFacts(local_postgresql=True, old_var_lib_pgsql_data=False)))

    assert reporting.create_report.called == 1
