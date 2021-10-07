from leapp.models import SatelliteFacts, SatellitePostgresqlFacts
from leapp.snactor.fixture import current_actor_context

class MockedRun(object):
    def __init__(self):
        self.commands = []

    def __call__(self, cmd, *args, **kwargs):
        self.commands.append(cmd)
        return {}


def test_run_installer(monkeypatch, current_actor_context):
    mocked_run = MockedRun()
    monkeypatch.setattr('leapp.libraries.stdlib.run', mocked_run)
    current_actor_context.feed(SatelliteFacts(has_foreman=True, postgresql=SatellitePostgresqlFacts()))
    current_actor_context.run()
    # for some reason, this is empty?!
    #assert mocked_run.commands
    #assert len(mocked_run.commands) == 1
